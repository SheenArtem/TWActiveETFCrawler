"""
報告管理模組 - 統一管理所有格式的報告生成
"""
from pathlib import Path
from typing import Dict, List
import json
from loguru import logger
from .holdings_analyzer import HoldingsAnalyzer, HoldingChange
from .report_generator import HTMLReportGenerator


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
    
    def generate_all_reports(
        self, 
        changes_dict: Dict[str, List[HoldingChange]], 
        date: str,
        append_txt: bool = False
    ):
        """
        生成所有格式的報告
        
        Args:
            changes_dict: ETF代碼 -> 變動列表的字典
            date: 報告日期
            append_txt: 是否追加到 TXT 報告（用於同一天多次更新）
        """
        if not changes_dict:
            logger.info("No changes to report")
            return
        
        # 取得 ETF 資訊
        etf_info = self.db.get_active_etfs()
        etf_info_dict = {e['etf_code']: e['etf_name'] for e in etf_info}
        
        # 1. 生成純文字報告（向後兼容）
        txt_report = self.analyzer.generate_report(changes_dict, date)
        txt_file = self.reports_dir / f"changes_{date}.txt"
        mode = 'a' if append_txt and txt_file.exists() else 'w'
        with open(txt_file, mode, encoding='utf-8') as f:
            if mode == 'a':
                f.write('\n')
            f.write(txt_report)
        logger.info(f"TXT report saved to: {txt_file}")
        
        # 2. 生成 Markdown 報告
        md_report = self.analyzer.generate_markdown_report(changes_dict, date)
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
            etf_info_dict
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
