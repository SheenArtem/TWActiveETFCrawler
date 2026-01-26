"""
工具函數模組
"""
import sqlite3
from datetime import datetime, timedelta
from typing import List
import os
from loguru import logger


def is_active_etf(code: str) -> bool:
    """
    判斷股票代碼是否為主動式ETF（代碼A結尾）
    
    Args:
        code: 股票代碼
        
    Returns:
        bool: 是否為主動式ETF
    """
    return code.strip().upper().endswith('A')


def format_date(date_obj: datetime, format_string: str = '%Y-%m-%d') -> str:
    """
    格式化日期
    
    Args:
        date_obj: 日期物件
        format_string: 格式字串
        
    Returns:
        str: 格式化後的日期字串
    """
    return date_obj.strftime(format_string)


def get_trading_days(start_date: datetime, end_date: datetime) -> List[datetime]:
    """
    計算交易日（簡化版，排除週末）
    注意：此版本不包含台灣國定假日，實際使用可能需要更完整的交易日曆
    
    Args:
        start_date: 開始日期
        end_date: 結束日期
        
    Returns:
        List[datetime]: 交易日列表
    """
    trading_days = []
    current_date = start_date
    
    while current_date <= end_date:
        # 排除週末（週六=5, 週日=6）
        if current_date.weekday() < 5:
            trading_days.append(current_date)
        current_date += timedelta(days=1)
    
    return trading_days


def cleanup_old_data(db_path: str, days_to_keep: int = 365) -> dict:
    """
    清理超過指定天數的資料
    
    Args:
        db_path: SQLite資料庫路徑
        days_to_keep: 保留天數，預設365天
    
    Returns:
        dict: 清理結果統計
    """
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    cutoff_str = cutoff_date.strftime('%Y-%m-%d')
    
    # 檢查檔案是否存在
    if not os.path.exists(db_path):
        logger.warning(f"Database file not found: {db_path}")
        return {
            'records_deleted': 0,
            'size_before_mb': 0,
            'size_after_mb': 0,
            'size_saved_mb': 0,
            'cutoff_date': cutoff_str
        }
    
    # 獲取檔案大小（清理前）
    size_before = os.path.getsize(db_path) / (1024 * 1024)  # MB
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 計算將被刪除的筆數
        cursor.execute(
            "SELECT COUNT(*) FROM holdings WHERE date < ?",
            (cutoff_str,)
        )
        records_to_delete = cursor.fetchone()[0]
        
        # 刪除舊資料
        cursor.execute(
            "DELETE FROM holdings WHERE date < ?",
            (cutoff_str,)
        )
        conn.commit()
        
        # 釋放空間
        cursor.execute("VACUUM")
        conn.commit()
        
        logger.info(f"Deleted {records_to_delete} records older than {cutoff_str}")
        
    except sqlite3.OperationalError as e:
        logger.error(f"Database error during cleanup: {e}")
        records_to_delete = 0
    finally:
        conn.close()
    
    # 獲取檔案大小（清理後）
    size_after = os.path.getsize(db_path) / (1024 * 1024)  # MB
    
    result = {
        'records_deleted': records_to_delete,
        'size_before_mb': round(size_before, 2),
        'size_after_mb': round(size_after, 2),
        'size_saved_mb': round(size_before - size_after, 2),
        'cutoff_date': cutoff_str
    }
    
    logger.info(f"Cleanup complete: {result}")
    return result


def setup_logging(log_path: str, log_level: str = "INFO"):
    """
    設定日誌記錄
    
    Args:
        log_path: 日誌檔案路徑
        log_level: 日誌級別
    """
    from loguru import logger
    import sys
    
    # 移除預設的 handler
    logger.remove()
    
    # 加入 console handler（彩色輸出）
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level=log_level
    )
    
    # 加入 file handler
    logger.add(
        log_path,
        rotation="10 MB",  # 檔案達到 10 MB 時輪換
        retention="30 days",  # 保留 30 天
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}",
        level=log_level
    )
    
    return logger

def get_user_agent() -> str:
    """獲取隨機 User-Agent"""
    import random
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0"
    ]
    return random.choice(user_agents)
