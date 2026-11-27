"""
報告管理模組 - 統一管理所有格式的報告生成
"""
from datetime import date as date_type
from pathlib import Path
from typing import Dict, List, Optional
import json
import re
from loguru import logger
from .holdings_analyzer import HoldingsAnalyzer, HoldingChange
from .report_generator import HTMLReportGenerator
from .stock_markets import market_of
from .trading_calendar import trading_days_between


class ReportManager:
    """報告管理器 - 統一生成 TXT、Markdown 和 HTML 報告"""
    
    def __init__(self, db, reports_dir: Path, docs_dir: Path = None):
        """
        初始化報告管理器
        
        Args:
            db: 資料庫實例
            reports_dir: TXT 和 Markdown 報告輸出目錄
            docs_dir: HTML 報告輸出目錄（GitHub Pages）
        """
        self.db = db
        self.reports_dir = Path(reports_dir)
        self.docs_dir = Path(docs_dir) if docs_dir else Path("docs")
        self.analyzer = HoldingsAnalyzer(db)
        self.html_generator = HTMLReportGenerator(self.docs_dir)
        
        # 確保目錄存在
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)
    
    def build_etf_holdings(self, etf_info_dict: Dict[str, str], date: str) -> List[dict]:
        """
        組出報表用的持股資料，逐檔回退到各自最新可得的資料日期。

        逐檔取「不晚於報表日期的最新有資料日期」，而不是一律用報表日期。
        原因：各家投信的資料日期天然不同步（當日 PCF 的發布時間各家不同），
        且寫入層的日期錯位防護會擋掉來源未更新的當日資料。若固定用報表日期，
        那些落後一天的 ETF 會整檔從持股總覽消失——2026-08-05 實測會從 18 檔
        掉到 2 檔。改為逐檔回退後，每檔都顯示自己最新可得的持股，
        並以 data_date 標示該檔實際的資料日期。

        **這是持股總覽的唯一出口**：每日報表（generate_all_reports）與歷史回填
        （scripts/regenerate_reports.py）都必須走這裡。兩邊各寫一份的話，
        回填出來的報表會少掉 data_date，而且與逐檔回退的變動追蹤對不起來。

        Args:
            etf_info_dict: ETF 代碼 -> 名稱
            date: 報表日期（上限，不會取到晚於這天的資料）

        Returns:
            List[dict]: 每檔含 etf_code / etf_name / data_date / holdings
        """
        etf_holdings = []
        for etf_code in etf_info_dict.keys():
            holdings_date = self.db.get_latest_date_on_or_before(etf_code, date)
            holdings = (
                self.db.get_holdings_by_date(holdings_date, etf_code)
                if holdings_date else []
            )
            if not holdings:
                continue
            if holdings_date != date:
                logger.info(
                    f"{etf_code}: no holdings on {date}; "
                    f"falling back to its latest available date {holdings_date}"
                )
            etf_holdings.append({
                'etf_code': etf_code,
                'etf_name': etf_info_dict.get(etf_code, etf_code),
                'data_date': holdings_date,
                'holdings': [
                    {
                        'stock_code': h.get('stock_code', ''),
                        'stock_name': h.get('stock_name', ''),
                        # 'TW' 或 Bloomberg 市場後綴（US/JP/KS…）；海外部位的 lots 是「千股」不是「張」
                        'market': market_of(h.get('stock_code', '')),
                        'weight': h.get('weight', 0),
                        'lots': h.get('shares', 0) / 1000 if h.get('shares') else 0
                    }
                    for h in holdings
                ]
            })
        return etf_holdings

    def previous_report_data_dates(self, date: str) -> Dict[str, str]:
        """
        前一份已發布報表裡各 ETF 的資料日期。

        讀 docs 目錄中日期早於 date 的最新一份 `data_<日期>.json`。沒有前一份、或檔案讀不了時回空字典
        （等於不把任何 ETF 當成沒更新）。
        """
        earlier = sorted(
            m.group(1) for p in self.docs_dir.glob("data_*.json")
            if (m := re.fullmatch(r"data_(\d{4}-\d{2}-\d{2})\.json", p.name)) and m.group(1) < date
        )
        if not earlier:
            return {}
        previous_file = self.docs_dir / f"data_{earlier[-1]}.json"
        try:
            payload = json.loads(previous_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Cannot read previous report {previous_file} ({type(e).__name__}: {e}); "
                           f"no ETF will be treated as not updated")
            return {}
        return {
            e["etf_code"]: e["data_date"]
            for e in payload.get("etf_holdings", []) if e.get("data_date")
        }

    @staticmethod
    def find_stale_etfs(etf_holdings: List[dict], previous_data_dates: Dict[str, str], date: str) -> List[dict]:
        """
        自上一份報表以來沒有新資料的 ETF：這一份的資料日期與上一份報表相同。

        這些 ETF 的持股照樣留在持股總覽（最後一次抓到的內容），但它們的變動已經在資料日期
        第一次出現的那份報表列過，不再重列——否則來源停更幾週，同一批買賣就每天被報成當天的變動
        （2026-11 中信、聯博、兆豐停更期間，每日報表有 25～57% 的變動是這種舊資料）。
        固定落後一天的來源（第一金、00988A）每天資料日期都會前進，不在此列。

        Returns:
            List[dict]: 每檔含 etf_code / etf_name / data_date / trading_days_behind（資料日期落後報表日期幾個交易日）
        """
        report_day = date_type.fromisoformat(date)
        stale = []
        for etf in etf_holdings:
            data_date = etf.get('data_date')
            if data_date and previous_data_dates.get(etf['etf_code']) == data_date:
                stale.append({
                    'etf_code': etf['etf_code'],
                    'etf_name': etf.get('etf_name', etf['etf_code']),
                    'data_date': data_date,
                    'trading_days_behind': trading_days_between(date_type.fromisoformat(data_date), report_day),
                })
        return stale

    def generate_all_reports(
        self,
        changes_dict: Dict[str, List[HoldingChange]],
        date: str,
        append_txt: bool = False,
        previous_data_dates: Optional[Dict[str, str]] = None
    ):
        """
        生成所有格式的報告

        Args:
            changes_dict: ETF代碼 -> 變動列表的字典
            date: 報告日期
            append_txt: 是否追加到 TXT 報告（用於同一天多次更新）
            previous_data_dates: 上一份報表各 ETF 的資料日期，用來判斷哪些 ETF 沒有新資料；
                不給就讀 docs 目錄裡的前一份報表（重生歷史報表的工具要自己給，見 scripts/pinned_reports.py）
        """
        if not changes_dict:
            logger.info("No changes to report")
            return

        # 取得 ETF 資訊
        etf_info = self.db.get_active_etfs()
        etf_info_dict = {e['etf_code']: e['etf_name'] for e in etf_info}

        # 持股總覽先組好：要靠各檔的 data_date 找出自上一份報表以來沒有新資料的 ETF，
        # 它們的變動不重列（見 find_stale_etfs），三種格式的報告與索引都用過濾後的變動。
        etf_holdings = self.build_etf_holdings(etf_info_dict, date)
        if previous_data_dates is None:
            previous_data_dates = self.previous_report_data_dates(date)
        stale_etfs = self.find_stale_etfs(etf_holdings, previous_data_dates, date)
        if stale_etfs:
            stale_codes = {e['etf_code'] for e in stale_etfs}
            changes_dict = {code: changes for code, changes in changes_dict.items() if code not in stale_codes}
            logger.info(
                "No new data since the previous report (changes not repeated): "
                + ", ".join(f"{e['etf_code']}@{e['data_date']}" for e in stale_etfs)
            )

        # 1. 生成純文字報告（向後兼容）
        txt_report = self.analyzer.generate_report(changes_dict, date, stale_etfs)
        txt_file = self.reports_dir / f"changes_{date}.txt"
        mode = 'a' if append_txt and txt_file.exists() else 'w'
        with open(txt_file, mode, encoding='utf-8') as f:
            if mode == 'a':
                f.write('\n')
            f.write(txt_report)
        logger.info(f"TXT report saved to: {txt_file}")
        
        # 2. 生成 Markdown 報告
        md_report = self.analyzer.generate_markdown_report(changes_dict, date, stale_etfs)
        md_file = self.reports_dir / f"changes_{date}.md"
        
        # Markdown 不追加，每次都完整生成
        # 如果需要合併同一天的多個更新，需要先讀取現有資料
        if append_txt and md_file.exists():
            # 讀取現有的 changes_dict 並合併
            # 這裡簡化處理：直接覆蓋
            pass
        
        with open(md_file, 'w', encoding='utf-8') as f:
            f.write(md_report)
        logger.info(f"Markdown report saved to: {md_file}")
        
        # 3. 生成 HTML 報告（GitHub Pages）
        html_file = self.html_generator.generate_daily_report(
            changes_dict,
            date,
            etf_info_dict,
            etf_holdings,
            stale_etfs
        )
        logger.info(f"HTML report saved to: {html_file}")
        
        # 4. 更新報告索引（用於網頁顯示）
        self._update_reports_index(changes_dict, date)
    
    def _update_reports_index(self, changes_dict: Dict[str, List[HoldingChange]], date: str):
        """
        更新報告索引檔案
        
        Args:
            changes_dict: ETF代碼 -> 變動列表的字典
            date: 報告日期
        """
        index_file = self.docs_dir / "reports_index.json"
        
        # 讀取現有索引
        if index_file.exists():
            with open(index_file, 'r', encoding='utf-8') as f:
                try:
                    reports = json.load(f)
                except json.JSONDecodeError:
                    reports = []
        else:
            reports = []
        
        # 檢查是否已存在該日期的報告
        existing_index = next((i for i, r in enumerate(reports) if r['date'] == date), None)
        
        # 計算統計資訊
        total_changes = sum(len(changes) for changes in changes_dict.values())
        etf_codes = list(changes_dict.keys())
        
        new_report = {
            'date': date,
            'etf_count': len(changes_dict),
            'total_changes': total_changes,
            'etfs': etf_codes
        }
        
        if existing_index is not None:
            # 更新現有記錄
            reports[existing_index] = new_report
        else:
            # 新增記錄
            reports.insert(0, new_report)
        
        # 按日期排序（最新的在前）
        reports.sort(key=lambda x: x['date'], reverse=True)
        
        # 只保留最近 90 天的記錄
        reports = reports[:90]
        
        # 儲存索引
        with open(index_file, 'w', encoding='utf-8') as f:
            json.dump(reports, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Reports index updated: {len(reports)} reports")
