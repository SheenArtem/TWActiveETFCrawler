"""
資料庫管理模組
"""
import sqlite3
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
from loguru import logger


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
    
    def insert_holdings(self, holdings: List[Dict[str, Any]]):
        """
        插入或更新持股明細
        
        當同一 ETF、股票、日期的記錄已存在時，會更新為最新資料。
        這允許一天內多次執行爬蟲時能夠更新資料。
        
        Args:
            holdings: 持股明細列表
        
        Returns:
            int: 新插入或更新的記錄數
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        inserted_count = 0
        updated_count = 0
        
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
                
                # 使用 REPLACE (等同於 DELETE + INSERT)
                cursor.execute("""
                    INSERT OR REPLACE INTO holdings 
                    (etf_code, stock_code, stock_name, shares, market_value, weight, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
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
