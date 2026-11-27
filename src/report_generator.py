"""
報告生成器模組 - 生成 HTML 格式的視覺化報告
"""
from typing import Dict, List, Optional
from pathlib import Path
import json
from datetime import date as date_type, datetime, timedelta, timezone
from .holdings_analyzer import HoldingChange
from .report_page import render_report_page
from .stock_markets import market_of
from .trading_calendar import confirmed_previous_trading_day


REPORT_SCHEMA_VERSION = 2


class HTMLReportGenerator:
    """產生持股日報的公開 JSON 與靜態頁面。"""
    
    def __init__(self, output_dir: Path = None):
        """
        初始化報告生成器
        
        Args:
            output_dir: 輸出目錄，預設為 docs/
        """
        self.output_dir = output_dir or Path("docs")
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_dashboard_data(
        self, 
        changes_dict: Dict[str, List[HoldingChange]], 
        date: str,
        etf_info_dict: Dict[str, str],
        etf_holdings: List[dict] = None,
        stale_etfs: List[dict] = None,
        *,
        report_schema: int = REPORT_SCHEMA_VERSION,
        previous_report_date: Optional[str] = None,
    ) -> dict:
        """
        生成儀表板所需的 JSON 資料

        Args:
            changes_dict: ETF代碼 -> 變動列表的字典（已不含沒有新資料的 ETF）
            date: 報告日期
            etf_info_dict: ETF代碼 -> ETF名稱的字典
            stale_etfs: 自上一份報表以來沒有新資料的 ETF（ReportManager.find_stale_etfs 的回傳值）。
                有才會寫進 `stale_etfs` 欄位；沒有時輸出與加這個欄位之前完全相同。

        Returns:
            dict: 包含所有圖表資料的字典
        """
        total_changes = sum(len(changes) for changes in changes_dict.values())

        def report_lots(shares, lots):
            # 每一股等於 0.001 張／千股。歷史格式保留原先的兩位小數。
            return shares / 1000 if report_schema >= 2 and shares is not None else round(lots, 2)

        def increases(change):
            if report_schema >= 2:
                return change.change_type == 'SHARES_UP'
            return change.lots_diff > 0
        
        # 1. 變動分布數據（圓餅圖）
        change_distribution = []
        for etf_code, changes in sorted(changes_dict.items()):
            etf_name = etf_info_dict.get(etf_code, etf_code)
            change_distribution.append({
                'etf_code': etf_code,
                'etf_name': etf_name,
                'count': len(changes)
            })
        
        # 2. 熱門調整股票統計
        stock_changes = {}  # stock_code -> {name, up_count, down_count, net_change, etf_details}
        
        for etf_code, changes in changes_dict.items():
            etf_name = etf_info_dict.get(etf_code, etf_code)
            for change in changes:
                if change.change_type in ['SHARES_UP', 'SHARES_DOWN']:
                    code = change.stock_code
                    if code not in stock_changes:
                        stock_changes[code] = {
                            'name': change.stock_name,
                            'up_count': 0,
                            'down_count': 0,
                            'net_change': 0,
                            'etf_details': []
                        }
                    
                    # 記錄 ETF 調整詳情
                    etf_detail = {
                        'etf_code': etf_code,
                        'etf_name': etf_name,
                        'adjustment': report_lots(change.shares_diff, change.lots_diff),
                        'new_lots': report_lots(change.new_shares, change.new_lots)
                    }
                    stock_changes[code]['etf_details'].append(etf_detail)
                    stock_changes[code]['net_change'] += etf_detail['adjustment'] if report_schema >= 2 else change.lots_diff
                    
                    if change.change_type == 'SHARES_UP':
                        stock_changes[code]['up_count'] += 1
                    else:
                        stock_changes[code]['down_count'] += 1
        
        # 補充權重資訊
        if etf_holdings:
            for stock_code, stock_data in stock_changes.items():
                for etf_detail in stock_data['etf_details']:
                    etf_code = etf_detail['etf_code']
                    # 在 etf_holdings 中找到對應的 ETF
                    for etf in etf_holdings:
                        if etf['etf_code'] == etf_code:
                            # 在該 ETF 的持股中找到對應的股票
                            for holding in etf.get('holdings', []):
                                if holding.get('stock_code') == stock_code:
                                    etf_detail['weight'] = holding.get('weight', 0)
                                    etf_detail['lots'] = holding.get('lots', 0)
                                    break
                            break
        
        # 排序：按調整次數
        hot_stocks = [
            {
                'stock_code': code,
                'stock_name': data['name'],
                'market': market_of(code),
                'total_adjustments': data['up_count'] + data['down_count'],
                'net_change': round(data['net_change'], 3 if report_schema >= 2 else 2),
                'etf_details': data['etf_details']
            }
            for code, data in stock_changes.items()
        ]
        hot_stocks.sort(key=lambda x: x['total_adjustments'], reverse=True)
        hot_stocks = hot_stocks[:10]  # 取前 10 名
        
        # 3. 詳細變動列表
        #
        # 每筆帶 data_date：變動是逐檔比對「各自最新可得的資料日期」得出的
        # （HoldingsAnalyzer.detect_changes_batch），來源停更時同一筆變動會在
        # 連續多個報表日期重複出現。沒有這個欄位，下游無法分辨「同一筆重複出現」
        # 與「真的又動了一次」，個股反查的買賣張數就會把同一次調整重複計入。
        # 來源與持股總覽同一個解析結果（get_latest_date_on_or_before），故直接沿用。
        holdings_date_map = {
            e['etf_code']: e.get('data_date')
            for e in (etf_holdings or [])
        }

        detailed_changes = []
        for etf_code, changes in sorted(changes_dict.items()):
            etf_name = etf_info_dict.get(etf_code, etf_code)

            # 分類變動
            added = [c for c in changes if c.change_type == 'ADDED']
            removed = [c for c in changes if c.change_type == 'REMOVED']
            modified = [c for c in changes if c.change_type not in ['ADDED', 'REMOVED']]

            etf_changes = {
                'etf_code': etf_code,
                'etf_name': etf_name,
                'data_date': holdings_date_map.get(etf_code, None if report_schema >= 2 else date),
                'total_changes': len(changes),
                # market：'TW' 或 Bloomberg 市場後綴（US/JP/KS…）。海外成分股（00988A）的
                # lots 數值同樣是 股數/1000，但單位是「千股」不是「張」，前端據此換單位名稱。
                'added': [
                    {
                        'stock_code': c.stock_code,
                        'stock_name': c.stock_name,
                        'market': market_of(c.stock_code),
                        'lots': report_lots(c.new_shares, c.new_lots)
                    }
                    for c in added
                ],
                'removed': [
                    {
                        'stock_code': c.stock_code,
                        'stock_name': c.stock_name,
                        'market': market_of(c.stock_code),
                        'lots': report_lots(c.old_shares, c.old_lots)
                    }
                    for c in removed
                ],
                'modified': [
                    {
                        'stock_code': c.stock_code,
                        'stock_name': c.stock_name,
                        'market': market_of(c.stock_code),
                        'old_lots': report_lots(c.old_shares, c.old_lots),
                        'new_lots': report_lots(c.new_shares, c.new_lots),
                        'diff': report_lots(c.shares_diff, c.lots_diff),
                        'direction': 'up' if increases(c) else 'down'
                    }
                    for c in modified
                ]
            }
            detailed_changes.append(etf_changes)
        
        data = {
            'date': date,
            # 以 timezone-aware 的 UTC 轉台北時區，主機是否為 UTC 都正確。
            # 舊寫法 datetime.now()+8h 假設主機為 UTC，在本機(已是 UTC+8)會多加 8 小時變成隔日。
            'update_time': datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S'),  # 台北時間 (UTC+8)
            'summary': {
                'total_etfs': len(changes_dict),
                'total_changes': total_changes
            },
            'change_distribution': change_distribution,
            'hot_stocks': hot_stocks,
            'detailed_changes': detailed_changes,
            'etf_holdings': etf_holdings or []
        }
        if stale_etfs:
            data['stale_etfs'] = stale_etfs
        if report_schema >= 2:
            previous_session = confirmed_previous_trading_day(date_type.fromisoformat(date))
            data['report_schema_version'] = report_schema
            data['previous_trading_date'] = previous_session.isoformat() if previous_session else None
            data['previous_report_date'] = previous_report_date
        return data

    def generate_daily_report(
        self,
        changes_dict: Dict[str, List[HoldingChange]],
        date: str,
        etf_info_dict: Dict[str, str],
        etf_holdings: List[dict] = None,
        stale_etfs: List[dict] = None,
        *,
        report_schema: int = REPORT_SCHEMA_VERSION,
        previous_report_date: Optional[str] = None,
    ) -> Path:
        """
        生成每日報告 HTML 檔案
        
        Args:
            changes_dict: ETF代碼 -> 變動列表的字典
            date: 報告日期
            etf_info_dict: ETF代碼 -> ETF名稱的字典
            etf_holdings: ETF 持股明細列表（可選）
            stale_etfs: 自上一份報表以來沒有新資料的 ETF（可選）

        Returns:
            Path: 生成的 HTML 檔案路徑
        """
        # 生成 JSON 資料
        data = self.generate_dashboard_data(changes_dict, date, etf_info_dict, etf_holdings, stale_etfs,
                                            report_schema=report_schema, previous_report_date=previous_report_date)
        
        # 儲存 JSON 資料檔
        json_file = self.output_dir / f"data_{date}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 生成 HTML 報告
        html_file = self.output_dir / f"report_{date}.html"
        html_content = render_report_page(data, self.output_dir)
        
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return html_file
