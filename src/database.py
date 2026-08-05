"""
資料庫管理模組
"""
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple
from datetime import datetime
from loguru import logger

from .stock_names import canonical_name
from .config import REJECT_DUPLICATE_OF_PREVIOUS_DAY


class Database:
    """SQLite 資料庫管理類別"""
    
    def __init__(self, db_path: str):
        """
        初始化資料庫
        
        Args:
            db_path: 資料庫檔案路徑
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self):
        """初始化資料庫表格"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # 建立 ETF 清單表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS etf_list (
                etf_code TEXT PRIMARY KEY,
                etf_name TEXT,
                issuer TEXT,
                listing_date TEXT,
                last_updated TEXT
            )
        """)
        
        # 建立持股明細表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS holdings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                etf_code TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                shares INTEGER,
                market_value REAL,
                weight REAL,
                date TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(etf_code, stock_code, date)
            )
        """)
        
        # 建立索引以加速查詢
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_holdings_etf_code 
            ON holdings(etf_code)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_holdings_date 
            ON holdings(date)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_holdings_etf_date 
            ON holdings(etf_code, date)
        """)
        
        conn.commit()
        conn.close()
        
        logger.info(f"Database initialized at {self.db_path}")
    
    def get_connection(self) -> sqlite3.Connection:
        """獲取資料庫連線"""
        return sqlite3.connect(self.db_path)
    
    def insert_etf_list(self, etf_list: List[Dict[str, Any]]):
        """
        插入或更新 ETF 清單
        
        Args:
            etf_list: ETF 清單，每個項目包含 etf_code, etf_name 等欄位
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        for etf in etf_list:
            cursor.execute("""
                INSERT OR REPLACE INTO etf_list 
                (etf_code, etf_name, issuer, listing_date, last_updated)
                VALUES (?, ?, ?, ?, ?)
            """, (
                etf.get('etf_code'),
                etf.get('etf_name'),
                etf.get('issuer', ''),
                etf.get('listing_date', ''),
                current_time
            ))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Inserted/Updated {len(etf_list)} ETFs")
    
    @staticmethod
    def _holdings_fingerprint(rows) -> Set[Tuple[str, int, float]]:
        """
        建立持股指紋：{(股票代號, 股數, 權重)} 的集合。

        用 set 而非 list，避免排序差異或重複列造成假性不同；
        權重取到小數 4 位，容忍浮點表示誤差。
        """
        fingerprint = set()
        for stock_code, shares, weight in rows:
            fingerprint.add((
                str(stock_code),
                int(shares or 0),
                round(float(weight or 0), 4),
            ))
        return fingerprint

    def _previous_trading_date(self, cursor, etf_code: str, date: str) -> Optional[str]:
        """取該 ETF 在 date 之前、最近一個有資料的交易日"""
        cursor.execute(
            "SELECT MAX(date) FROM holdings WHERE etf_code=? AND date<?",
            (etf_code, date),
        )
        row = cursor.fetchone()
        return row[0] if row and row[0] else None

    def _duplicates_previous_day(
        self, cursor, etf_code: str, date: str, incoming_rows
    ) -> Tuple[bool, Optional[str]]:
        """
        判斷待寫入的持股是否與前一交易日逐列完全相同。

        Returns:
            (是否重複, 前一交易日)。無前一交易日或前一日無資料時回傳 (False, prev)。
        """
        prev_date = self._previous_trading_date(cursor, etf_code, date)
        if not prev_date:
            return False, None

        cursor.execute(
            "SELECT stock_code, shares, weight FROM holdings WHERE etf_code=? AND date=?",
            (etf_code, prev_date),
        )
        previous = self._holdings_fingerprint(cursor.fetchall())
        if not previous:
            return False, prev_date

        return self._holdings_fingerprint(incoming_rows) == previous, prev_date

    def _reject_duplicate_snapshots(
        self, cursor, holdings: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        日期錯位防護：剔除「與前一交易日完全相同」的 (ETF, 日期) 群組。

        投信當日 PCF 尚未發布時，用請求日期當資料日期的 scraper 會把前一日內容
        寫成當日。逐列完全相同即視為來源未更新，不寫入並記錄警告，
        讓當日資料維持缺漏，而非留下假資料。

        **只對「用請求日期」的來源生效。** 若群組內每一列都帶
        `source_dated=True`（scraper 已從來源本身取得資料日期），則跳過防護：
        那種來源不會有錯位，防護對它只會誤擋，而且誤擋無法補救——來源日期
        會往前走（隔天只給隔天的檔案），被擋掉的那天再也抓不回來。
        用請求日期的來源則相反，被擋掉後當天稍後的班次還有機會補上真實資料。

        `source_dated` 由 scraper 在「確實解析到來源日期」時才設 True；
        解析失敗退回請求日期時必須不設或設 False。夾住過的日期（如摩根 PCF
        估值日夾到請求日）也不算 source_dated——夾住後就失去辨識來源是否
        更新的能力，仍需要防護。

        Returns:
            過濾後的持股列表；未啟用或無重複時原樣回傳。
        """
        grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for holding in holdings:
            grouped[(holding.get('etf_code'), holding.get('date'))].append(holding)

        rejected: Set[Tuple[str, str]] = set()
        for (etf_code, date), rows in grouped.items():
            if not etf_code or not date:
                continue
            # all() 而非 any()：混合來源時保守地繼續防護
            if rows and all(r.get('source_dated') for r in rows):
                logger.debug(
                    f"Skipping duplicate guard for {etf_code} {date}: "
                    f"date came from the source itself"
                )
                continue
            incoming = [
                (r.get('stock_code'), r.get('shares'), r.get('weight')) for r in rows
            ]
            is_duplicate, prev_date = self._duplicates_previous_day(
                cursor, etf_code, date, incoming
            )
            if is_duplicate:
                rejected.add((etf_code, date))
                logger.warning(
                    f"Rejected {etf_code} {date}: {len(rows)} holdings are identical "
                    f"row-for-row to {prev_date}; source has likely not published "
                    f"today's PCF yet. Nothing written for {date}."
                )

        if not rejected:
            return holdings

        return [
            h for h in holdings
            if (h.get('etf_code'), h.get('date')) not in rejected
        ]

    def insert_holdings(self, holdings: List[Dict[str, Any]]):
        """
        插入或更新持股明細

        當同一 ETF、股票、日期的記錄已存在時，會更新為最新資料。
        這允許一天內多次執行爬蟲時能夠更新資料。

        寫入前會執行日期錯位防護（見 _reject_duplicate_snapshots），
        可用環境變數 REJECT_DUPLICATE_OF_PREVIOUS_DAY=False 關閉。

        Args:
            holdings: 持股明細列表

        Returns:
            int: 新插入或更新的記錄數
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        inserted_count = 0
        updated_count = 0

        if REJECT_DUPLICATE_OF_PREVIOUS_DAY and holdings:
            holdings = self._reject_duplicate_snapshots(cursor, holdings)
            if not holdings:
                conn.close()
                return 0

        for holding in holdings:
            try:
                etf_code = holding.get('etf_code')
                stock_code = holding.get('stock_code')
                date = holding.get('date')
                
                # 檢查記錄是否已存在
                cursor.execute("""
                    SELECT shares, weight FROM holdings 
                    WHERE etf_code=? AND stock_code=? AND date=?
                """, (etf_code, stock_code, date))
                
                existing = cursor.fetchone()
                
                # UPSERT：同 (etf, stock, date) 已存在時就地更新數值欄位，
                # 但**保留原 created_at**——它的語意是「該列首次寫入的時間」。
                #
                # 舊寫法 INSERT OR REPLACE 等同 DELETE+INSERT，會把 created_at 蓋成當下，
                # 於是「來源沒更新、重寫同一個資料日期」也被 CI 早退守衛算成今天有進度。
                # source_dated 豁免的來源一多（台新/安聯/群益/摩根轉換後 14/19，已過
                # 70% 門檻），「全來源停更」的傍晚會誤達標而跳過後備班次，晚發布的
                # 來源（如聯博常在 18-19 點才更新當日檔）那天就永久缺資料。
                # 改成保留 created_at 後，守衛數的是「今天首次寫入的檔數」，
                # 停更重寫不計入，門檻語意恢復正確。
                cursor.execute("""
                    INSERT INTO holdings
                    (etf_code, stock_code, stock_name, shares, market_value, weight, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(etf_code, stock_code, date) DO UPDATE SET
                        stock_name=excluded.stock_name,
                        shares=excluded.shares,
                        market_value=excluded.market_value,
                        weight=excluded.weight
                """, (
                    etf_code,
                    stock_code,
                    holding.get('stock_name'),
                    holding.get('shares'),
                    holding.get('market_value'),
                    holding.get('weight'),
                    date
                ))
                
                if existing:
                    # 記錄已存在，檢查是否有實質變化
                    old_shares, old_weight = existing
                    new_shares = holding.get('shares')
                    new_weight = holding.get('weight', 0)
                    
                    if (old_shares != new_shares or abs(old_weight - new_weight) > 0.01):
                        updated_count += 1
                        logger.debug(f"Updated {etf_code} {stock_code} on {date}: "
                                   f"shares {old_shares}→{new_shares}, "
                                   f"weight {old_weight:.2f}%→{new_weight:.2f}%")
                else:
                    # 新記錄
                    inserted_count += 1
                    
            except sqlite3.Error as e:
                logger.error(f"Error inserting/updating holding: {e}")
        
        conn.commit()
        conn.close()
        
        if updated_count > 0:
            logger.info(f"Inserted {inserted_count} new holdings, "
                       f"Updated {updated_count} existing holdings "
                       f"(total processed: {len(holdings)})")
        else:
            logger.info(f"Inserted {inserted_count} new holdings "
                       f"(total processed: {len(holdings)})")
        
        return inserted_count + updated_count
    
    def get_active_etfs(self) -> List[Dict[str, Any]]:
        """
        獲取所有主動式 ETF
        
        Returns:
            List[Dict]: ETF 清單
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT etf_code, etf_name, issuer, listing_date 
            FROM etf_list 
            WHERE etf_code LIKE '%A'
            ORDER BY etf_code
        """)
        
        columns = [desc[0] for desc in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        conn.close()
        return results
    
    def get_holdings_by_date(self, date: str, etf_code: str = None) -> List[Dict[str, Any]]:
        """
        獲取指定日期的持股明細
        
        Args:
            date: 日期 (YYYY-MM-DD)
            etf_code: ETF 代碼（可選）
        
        Returns:
            List[Dict]: 持股明細
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if etf_code:
            cursor.execute("""
                SELECT * FROM holdings 
                WHERE date = ? AND etf_code = ?
                ORDER BY weight DESC
            """, (date, etf_code))
        else:
            cursor.execute("""
                SELECT * FROM holdings 
                WHERE date = ?
                ORDER BY etf_code, weight DESC
            """, (date,))
        
        columns = [desc[0] for desc in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

        conn.close()

        # 以代號為主鍵統一台股顯示名稱（各投信原始名稱格式不一）。
        # 此為所有報表輸出讀取持股名稱的單一出口，故在此正規化即可全面套用。
        for row in results:
            row['stock_name'] = canonical_name(
                row.get('stock_code', ''),
                row.get('stock_name', '')
            )

        return results

    def get_latest_date(self, etf_code: str = None) -> str:
        """
        獲取最新的資料日期
        
        Args:
            etf_code: ETF 代碼（可選）
        
        Returns:
            str: 最新日期，若無資料則返回 None
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if etf_code:
            cursor.execute("""
                SELECT MAX(date) FROM holdings WHERE etf_code = ?
            """, (etf_code,))
        else:
            cursor.execute("SELECT MAX(date) FROM holdings")
        
        result = cursor.fetchone()[0]
        conn.close()

        return result

    def get_latest_date_on_or_before(self, etf_code: str, date: str) -> Optional[str]:
        """
        取某 ETF 在 date（含）之前最新的有資料日期。

        各家投信的資料日期天然不同步：當日 PCF 的發布時間各家不同，早發布的當日就有，
        晚發布的要到收盤後才更新。改用來源日期後，報表日期那天本來就不會每檔 ETF 都有資料，
        用單一日期去撈會讓那些落後一天的 ETF 整檔從報表消失。報表因此改為
        逐檔取各自最新可得的日期（見 ReportManager.generate_all_reports）。

        Args:
            etf_code: ETF 代碼
            date: 上限日期（含），避免取到晚於報表日期的資料

        Returns:
            str: YYYY-MM-DD；該 ETF 在期限內完全沒有資料時回傳 None
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT MAX(date) FROM holdings WHERE etf_code=? AND date<=?",
            (etf_code, date),
        )
        result = cursor.fetchone()[0]
        conn.close()

        return result

    def get_previous_trading_date(self, current_date: str, etf_code: str = None) -> str:
        """
        獲取指定日期的前一個交易日
        
        Args:
            current_date: 當前日期 (YYYY-MM-DD)
            etf_code: ETF 代碼（可選）
        
        Returns:
            str: 前一個交易日，若無則返回 None
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if etf_code:
            cursor.execute("""
                SELECT MAX(date) FROM holdings 
                WHERE date < ? AND etf_code = ?
            """, (current_date, etf_code))
        else:
            cursor.execute("""
                SELECT MAX(date) FROM holdings 
                WHERE date < ?
            """, (current_date,))
        
        result = cursor.fetchone()[0]
        conn.close()
        
        return result
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        獲取資料庫統計資訊
        
        Returns:
            Dict: 統計資訊
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # ETF 數量
        cursor.execute("SELECT COUNT(*) FROM etf_list WHERE etf_code LIKE '%A'")
        etf_count = cursor.fetchone()[0]
        
        # 持股記錄總數
        cursor.execute("SELECT COUNT(*) FROM holdings")
        holdings_count = cursor.fetchone()[0]
        
        # 日期範圍
        cursor.execute("SELECT MIN(date), MAX(date) FROM holdings")
        date_range = cursor.fetchone()
        
        # 最新更新的 ETF
        cursor.execute("""
            SELECT etf_code, MAX(date) as latest_date 
            FROM holdings 
            GROUP BY etf_code 
            ORDER BY latest_date DESC 
            LIMIT 5
        """)
        latest_updates = cursor.fetchall()
        
        conn.close()
        
        return {
            'total_etfs': etf_count,
            'total_holdings': holdings_count,
            'date_range': {
                'start': date_range[0],
                'end': date_range[1]
            },
            'latest_updates': [
                {'etf_code': row[0], 'date': row[1]} 
                for row in latest_updates
            ]
        }
