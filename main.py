"""
台灣主動式 ETF 持股追蹤系統 - 主程式
"""
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import sys

from src.config import DB_FULL_PATH, LOG_PATH, LOG_LEVEL, DATA_RETENTION_DAYS, BASE_DIR
from src.database import Database
from src.etf_scraper import ETFScraper
from src.utils import setup_logging, cleanup_old_data, get_trading_days
from loguru import logger


def init_historical_data(months: int = 6):
    """
    初始化歷史資料（建立最近 N 個月的持股明細）
    
    Args:
        months: 要抓取的月份數
    """
    logger.info(f"Starting historical data initialization ({months} months)...")
    
    # 計算日期範圍
    end_date = datetime.now()
    start_date = end_date - timedelta(days=months * 30)
    
    # 獲取交易日
    trading_days = get_trading_days(start_date, end_date)
    logger.info(f"Found {len(trading_days)} trading days from {start_date.date()} to {end_date.date()}")
    
    # 初始化資料庫和爬蟲
    db = Database(DB_FULL_PATH)
    scraper = ETFScraper()
    
    # 1. 取得主動式 ETF 清單
    logger.info("Step 1: Fetching active ETF list...")
    etf_list = scraper.get_active_etf_list()
    if not etf_list:
        logger.error("No active ETFs found. Aborting.")
        return
    
    db.insert_etf_list(etf_list)
    logger.info(f"Inserted {len(etf_list)} ETFs into database")
    
    # 2. 逐一抓取每個 ETF 的歷史持股
    logger.info(f"Step 2: Fetching historical holdings for {len(etf_list)} ETFs...")
    
    total_holdings = 0
    for i, etf in enumerate(etf_list, 1):
        etf_code = etf['etf_code']
        logger.info(f"[{i}/{len(etf_list)}] Processing {etf_code} - {etf['etf_name']}")
        
        try:
            holdings = scraper.get_historical_holdings(
                etf_code,
                start_date.strftime('%Y-%m-%d'),
                end_date.strftime('%Y-%m-%d'),
                trading_days
            )
            
            if holdings:
                inserted = db.insert_holdings(holdings)
                total_holdings += inserted
                logger.info(f"{etf_code}: Inserted {inserted} new holdings")
            else:
                logger.warning(f"{etf_code}: No holdings data found")
        
        except Exception as e:
            logger.error(f"Error processing {etf_code}: {e}")
            continue
    
    # 3. 顯示統計資訊
    stats = db.get_statistics()
    logger.info(f"Initialization complete!")
    logger.info(f"Total ETFs: {stats['total_etfs']}")
    logger.info(f"Total holdings: {stats['total_holdings']}")
    logger.info(f"Date range: {stats['date_range']['start']} to {stats['date_range']['end']}")


def daily_update():
    """每日更新作業"""
    logger.info("Starting daily update...")
    
    # 初始化資料庫和爬蟲
    db = Database(DB_FULL_PATH)
    scraper = ETFScraper()
    
    # 獲取昨日日期（證交所資料通常 T+1 更新）
    yesterday = datetime.now() - timedelta(days=1)
    # 如果昨天是週末，往前推到週五
    while yesterday.weekday() >= 5:  # 5=週六, 6=週日
        yesterday -= timedelta(days=1)
    
    date_str = yesterday.strftime('%Y-%m-%d')
    logger.info(f"Fetching data for {date_str}")
    
    # 1. 更新 ETF 清單
    logger.info("Updating ETF list...")
    etf_list = scraper.get_active_etf_list()
    if etf_list:
        db.insert_etf_list(etf_list)
    
    # 2. 取得所有主動式 ETF
    active_etfs = db.get_active_etfs()
    logger.info(f"Found {len(active_etfs)} active ETFs to update")
    
    # 3. 逐一抓取持股明細
    total_inserted = 0
    for i, etf in enumerate(active_etfs, 1):
        etf_code = etf['etf_code']
        logger.info(f"[{i}/{len(active_etfs)}] Updating {etf_code}")
        
        try:
            holdings = scraper.get_etf_holdings(etf_code, date_str)
            if holdings:
                inserted = db.insert_holdings(holdings)
                total_inserted += inserted
        except Exception as e:
            logger.error(f"Error updating {etf_code}: {e}")
    
    logger.info(f"Daily update complete: {total_inserted} new holdings inserted")
    
    # 4. 清理舊資料
    logger.info("Cleaning up old data...")
    cleanup_result = cleanup_old_data(str(DB_FULL_PATH), DATA_RETENTION_DAYS)
    logger.info(f"Cleanup result: {cleanup_result}")
    
    # 5. 顯示統計
    stats = db.get_statistics()
    logger.info(f"Database statistics:")
    logger.info(f"  Total ETFs: {stats['total_etfs']}")
    logger.info(f"  Total holdings: {stats['total_holdings']}")
    logger.info(f"  Date range: {stats['date_range']['start']} to {stats['date_range']['end']}")


def show_stats():
    """顯示資料庫統計資訊"""
    db = Database(DB_FULL_PATH)
    stats = db.get_statistics()
    
    print("\n=== 資料庫統計 ===")
    print(f"主動式 ETF 數量: {stats['total_etfs']}")
    print(f"持股記錄總數: {stats['total_holdings']}")
    print(f"資料日期範圍: {stats['date_range']['start']} ~ {stats['date_range']['end']}")
    print(f"\n最近更新的 ETF:")
    for item in stats['latest_updates']:
        print(f"  {item['etf_code']}: {item['date']}")
    print()


def main():
    """主程式進入點"""
    parser = argparse.ArgumentParser(
        description="台灣主動式 ETF 持股追蹤系統",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        '--init',
        action='store_true',
        help='初始化模式：建立最近 N 個月的歷史資料'
    )
    
    parser.add_argument(
        '--months',
        type=int,
        default=6,
        help='初始化時要抓取的月份數（預設 6 個月）'
    )
    
    parser.add_argument(
        '--daily-update',
        action='store_true',
        help='每日更新模式：抓取昨日最新資料'
    )
    
    parser.add_argument(
        '--stats',
        action='store_true',
        help='顯示資料庫統計資訊'
    )
    
    args = parser.parse_args()
    
    # 設定日誌
    setup_logging(str(LOG_PATH), LOG_LEVEL)
    logger.info("=" * 60)
    logger.info("Taiwan Active ETF Tracker Started")
    logger.info(f"Database: {DB_FULL_PATH}")
    logger.info("=" * 60)
    
    try:
        if args.init:
            init_historical_data(args.months)
        elif args.daily_update:
            daily_update()
        elif args.stats:
            show_stats()
        else:
            parser.print_help()
            sys.exit(1)
    
    except KeyboardInterrupt:
        logger.warning("Program interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)
    
    logger.info("Program finished successfully")


if __name__ == "__main__":
    main()
