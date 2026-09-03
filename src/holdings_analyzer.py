"""
成分股變動分析模組
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from loguru import logger

from .stock_markets import lot_unit


@dataclass
class HoldingChange:
    """持股變動記錄"""
    change_type: str  # ADDED, REMOVED, SHARES_UP, SHARES_DOWN
    stock_code: str
    stock_name: str
    
    # 股數相關（股）
    old_shares: Optional[int] = None
    new_shares: Optional[int] = None
    shares_diff: Optional[int] = None
    
    # 張數相關（1張 = 1000股）
    old_lots: Optional[float] = None
    new_lots: Optional[float] = None
    lots_diff: Optional[float] = None


class HoldingsAnalyzer:
    """持股變動分析器"""
    
    def __init__(self, db):
        """
        初始化分析器
        
        Args:
            db: 資料庫實例
        """
        self.db = db
    
    @staticmethod
    def shares_to_lots(shares: int) -> float:
        """
        將股數轉換為張數
        
        Args:
            shares: 股數
            
        Returns:
            float: 張數（保留兩位小數）
        """
        return round(shares / 1000, 2) if shares else 0.0
    
    def compare_holdings(
        self, 
        yesterday_holdings: List[Dict[str, Any]], 
        today_holdings: List[Dict[str, Any]]
    ) -> List[HoldingChange]:
        """
        比較兩日持股，找出變動
        
        Args:
            yesterday_holdings: 昨日持股列表
            today_holdings: 今日持股列表
            
        Returns:
            List[HoldingChange]: 變動列表
        """
        # 建立字典方便查詢
        yesterday_stocks = {h['stock_code']: h for h in yesterday_holdings}
        today_stocks = {h['stock_code']: h for h in today_holdings}
        
        changes = []
        
        # 1. 檢測新增成分股
        for code in today_stocks:
            if code not in yesterday_stocks:
                holding = today_stocks[code]
                lots = self.shares_to_lots(holding.get('shares', 0))
                
                changes.append(HoldingChange(
                    change_type='ADDED',
                    stock_code=code,
                    stock_name=holding.get('stock_name', ''),
                    new_shares=holding.get('shares', 0),
                    new_lots=lots
                ))
        
        # 2. 檢測移除成分股
        for code in yesterday_stocks:
            if code not in today_stocks:
                holding = yesterday_stocks[code]
                lots = self.shares_to_lots(holding.get('shares', 0))
                
                changes.append(HoldingChange(
                    change_type='REMOVED',
                    stock_code=code,
                    stock_name=holding.get('stock_name', ''),
                    old_shares=holding.get('shares', 0),
                    old_lots=lots
                ))
        
        # 3. 檢測股數變動
        for code in yesterday_stocks:
            if code in today_stocks:
                old_holding = yesterday_stocks[code]
                new_holding = today_stocks[code]
                
                old_shares = old_holding.get('shares', 0)
                new_shares = new_holding.get('shares', 0)
                shares_diff = new_shares - old_shares
                
                old_lots = self.shares_to_lots(old_shares)
                new_lots = self.shares_to_lots(new_shares)
                lots_diff = new_lots - old_lots
                
                # 只要股數有任何變化就記錄（包括1股的變化）
                if shares_diff != 0:
                    change_type = 'SHARES_UP' if shares_diff > 0 else 'SHARES_DOWN'
                    
                    changes.append(HoldingChange(
                        change_type=change_type,
                        stock_code=code,
                        stock_name=new_holding.get('stock_name', ''),
                        old_shares=old_shares,
                        new_shares=new_shares,
                        shares_diff=shares_diff,
                        old_lots=old_lots,
                        new_lots=new_lots,
                        lots_diff=lots_diff
                    ))
        
        return changes
    
    def detect_changes(self, etf_code: str, current_date: str) -> Optional[List[HoldingChange]]:
        """
        偵測特定ETF在指定日期的變動
        
        Args:
            etf_code: ETF代碼
            current_date: 當前日期 (YYYY-MM-DD)
            
        Returns:
            List[HoldingChange] or None: 變動列表，若無前一日資料則返回 None
        """
        # 取得前一個交易日
        previous_date = self.db.get_previous_trading_date(current_date, etf_code)
        
        if not previous_date:
            logger.debug(f"No previous data found for {etf_code} before {current_date}")
            return None
        
        # 取得兩日的持股明細
        yesterday_holdings = self.db.get_holdings_by_date(previous_date, etf_code)
        today_holdings = self.db.get_holdings_by_date(current_date, etf_code)
        
        if not today_holdings:
            logger.warning(f"No holdings found for {etf_code} on {current_date}")
            return None
        
        # 比較變動
        changes = self.compare_holdings(yesterday_holdings, today_holdings)
        
        return changes if changes else None
    
    def detect_changes_batch(self, etf_codes: List[str], current_date: str) -> Dict[str, List[HoldingChange]]:
        """
        偵測指定列表中 ETF 的變動，逐檔取各自最新可得的資料日期

        各家投信的資料日期天然不同步（當日 PCF 的發布時間各家不同），加上寫入層的
        日期錯位防護會擋掉來源未更新的當日資料，所以 current_date 那天本來就不會每檔
        ETF 都有資料。若一律用 current_date 去比對，detect_changes() 會在「當日無持股」
        那個分支直接跳過，落後一天的 ETF 就永遠不會出現在變動報表裡。
        持股總覽已在 ReportManager 逐檔回退，這裡是另一半。

        代價：來源某天沒有前進時（歷史模擬中信 8 次、富邦 3 次），該檔會以同一個資料
        日期再被報一次。重複顯示比整檔消失好，且持股卡片上的 data_date 會標出實際日期。

        Args:
            etf_codes: ETF 代碼列表
            current_date: 報表日期，作為上限（不會取到晚於這天的資料）

        Returns:
            Dict[str, List[HoldingChange]]: ETF代碼 -> 變動列表的字典
        """
        all_changes = {}

        for etf_code in etf_codes:
            # 上限之前完全沒有資料的 ETF 直接跳過
            etf_date = self.db.get_latest_date_on_or_before(etf_code, current_date)
            if not etf_date:
                continue

            changes = self.detect_changes(etf_code, etf_date)

            if changes:
                all_changes[etf_code] = changes

        return all_changes

    def detect_all_changes(self, current_date: str) -> Dict[str, List[HoldingChange]]:
        """
        偵測所有ETF在指定日期的變動
        
        Args:
            current_date: 當前日期 (YYYY-MM-DD)
            
        Returns:
            Dict[str, List[HoldingChange]]: ETF代碼 -> 變動列表的字典
        """
        # 取得所有有資料的ETF
        etfs = self.db.get_active_etfs()
        etf_codes = [etf['etf_code'] for etf in etfs]
        
        return self.detect_changes_batch(etf_codes, current_date)
    
    def generate_report(self, changes_dict: Dict[str, List[HoldingChange]], date: str) -> str:
        """
        生成變動報告
        
        Args:
            changes_dict: ETF代碼 -> 變動列表的字典
            date: 報告日期
            
        Returns:
            str: 格式化的報告文字
        """
        if not changes_dict:
            return f"\n=== {date} ETF成分股變動報告 ===\n\n無變動\n"
        
        report_lines = [
            f"\n{'='*60}",
            f"=== {date} ETF成分股變動報告 ===",
            f"{'='*60}\n"
        ]
        
        total_changes = 0
        
        for etf_code, changes in sorted(changes_dict.items()):
            # 取得ETF名稱
            etf_info = self.db.get_active_etfs()
            etf_name = next((e['etf_name'] for e in etf_info if e['etf_code'] == etf_code), etf_code)
            
            report_lines.append(f"【{etf_code} - {etf_name}】")
            
            # 分類變動
            added = [c for c in changes if c.change_type == 'ADDED']
            removed = [c for c in changes if c.change_type == 'REMOVED']
            modified = [c for c in changes if c.change_type not in ['ADDED', 'REMOVED']]
            
            # 新增成分股
            if added:
                report_lines.append(f"  新增成分股 ({len(added)}):")
                for i, change in enumerate(added):
                    prefix = "├─" if i < len(added) - 1 else "└─"
                    report_lines.append(
                        f"    {prefix} {change.stock_code} {change.stock_name} "
                        f"(持股: {change.new_lots:.2f}{lot_unit(change.stock_code)})"
                    )
                report_lines.append("")
            
            # 移除成分股
            if removed:
                report_lines.append(f"  移除成分股 ({len(removed)}):")
                for i, change in enumerate(removed):
                    prefix = "├─" if i < len(removed) - 1 else "└─"
                    report_lines.append(
                        f"    {prefix} {change.stock_code} {change.stock_name} "
                        f"(昨日持股: {change.old_lots:.2f}{lot_unit(change.stock_code)})"
                    )
                report_lines.append("")
            
            # 持股變動
            if modified:
                report_lines.append(f"  持股變動 ({len(modified)}):")
                for i, change in enumerate(modified):
                    prefix = "├─" if i < len(modified) - 1 else "└─"
                    
                    # 持股變動（台股「張」、海外成分股「千股」，見 src/stock_markets.py）
                    lots_arrow = "▲" if change.lots_diff > 0 else "▼"
                    unit = lot_unit(change.stock_code)
                    report_lines.append(
                        f"    {prefix} {change.stock_code} {change.stock_name} "
                        f"持股: {change.old_lots:.2f}{unit} → {change.new_lots:.2f}{unit} "
                        f"({lots_arrow}{abs(change.lots_diff):.2f}{unit})"
                    )
                
                report_lines.append("")
            
            total_changes += len(changes)
        
        # 總結
        report_lines.append(f"總計：處理 {len(changes_dict)} 個ETF，發現 {total_changes} 筆變動")
        report_lines.append(f"{'='*60}\n")
        
        return "\n".join(report_lines)

    def generate_markdown_report(self, changes_dict: Dict[str, List[HoldingChange]], date: str) -> str:
        """
        生成 Markdown 格式的變動報告（提案 A：簡潔列表式）
        
        Args:
            changes_dict: ETF代碼 -> 變動列表的字典
            date: 報告日期
            
        Returns:
            str: Markdown 格式的報告
        """
        from datetime import datetime, timedelta
        
        if not changes_dict:
            return f"# ETF 持股變動追蹤 📊\n\n> 最後更新：{date}\n\n## {date} 變動摘要\n\n**本日無變動**\n"
        
        total_changes = sum(len(changes) for changes in changes_dict.values())
        # 台北时间 (UTC+8)
        current_time = (datetime.utcnow() + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')
        
        md_lines = [
            "# ETF 持股變動追蹤 📊\n",
            f"> 最後更新：{current_time}\n",
            f"## {date} 變動摘要\n",
            f"**本日共 {len(changes_dict)} 檔 ETF 發生 {total_changes} 筆變動**\n"
        ]
        
        for etf_code, changes in sorted(changes_dict.items()):
            # 取得ETF名稱
            etf_info = self.db.get_active_etfs()
            etf_name = next((e['etf_name'] for e in etf_info if e['etf_code'] == etf_code), etf_code)
            
            # 分類變動
            added = [c for c in changes if c.change_type == 'ADDED']
            removed = [c for c in changes if c.change_type == 'REMOVED']
            modified = [c for c in changes if c.change_type not in ['ADDED', 'REMOVED']]
            
            # 使用折疊區塊
            md_lines.append(f'<details open>')
            md_lines.append(f'<summary><b>{etf_code}</b> {etf_name} ({len(changes)} 筆變動)</summary>\n')
            
            # 新增成分股
            if added:
                md_lines.append("### ➕ 新增成分股\n")
                md_lines.append("| 股票代碼 | 股票名稱 | 持股 |")
                md_lines.append("|---------|---------|---------|")
                for change in added:
                    md_lines.append(f"| {change.stock_code} | {change.stock_name} | {change.new_lots:.2f}{lot_unit(change.stock_code)} |")
                md_lines.append("")
            
            # 移除成分股
            if removed:
                md_lines.append("### ➖ 移除成分股\n")
                md_lines.append("| 股票代碼 | 股票名稱 | 原持股 |")
                md_lines.append("|---------|---------|----------|")
                for change in removed:
                    md_lines.append(f"| {change.stock_code} | {change.stock_name} | {change.old_lots:.2f}{lot_unit(change.stock_code)} |")
                md_lines.append("")
            
            # 持股變動
            if modified:
                md_lines.append("### 📊 持股變動\n")
                md_lines.append("| 股票代碼 | 股票名稱 | 變動 | 原持股 | 新持股 | 增減 |")
                md_lines.append("|---------|---------|-----|--------|--------|------|")
                for change in modified:
                    emoji = "📈" if change.lots_diff > 0 else "📉"
                    sign = "+" if change.lots_diff > 0 else ""
                    unit = lot_unit(change.stock_code)
                    md_lines.append(
                        f"| {change.stock_code} | {change.stock_name} | {emoji} | "
                        f"{change.old_lots:,.0f}{unit} | {change.new_lots:,.0f}{unit} | "
                        f"{sign}{change.lots_diff:,.0f}{unit} |"
                    )
                md_lines.append("")
            
            md_lines.append("</details>\n")
        
        # 添加說明
        md_lines.append("---\n")
        md_lines.append("### 📝 說明\n")
        md_lines.append("- 📈 表示持股增加\n")
        md_lines.append("- 📉 表示持股減少\n")
        md_lines.append("- 海外成分股（代號含 Bloomberg 市場後綴，如 `SNDK US`）以「千股」計，1 千股＝1000 股\n")
        md_lines.append("- 資料來源：各投信公司官網\n")
        md_lines.append(f"- 報告生成時間：{current_time}\n")
        
        return "\n".join(md_lines)
