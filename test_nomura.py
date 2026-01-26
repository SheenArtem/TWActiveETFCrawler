"""
測試野村投信 ETF 爬蟲
抓取 00980A 的每日成分股資料
"""
import sys
from pathlib import Path
from datetime import datetime

# 加入 src 目錄到 Python 路徑
sys.path.insert(0, str(Path(__file__).parent))

from src.nomura_scraper import NomuraScraper
from src.database import Database
from src.config import DB_FULL_PATH
from loguru import logger

# 設定簡單的日誌輸出
logger.remove()
logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>")

def test_etf_mapping():
    """測試 ETF 代碼對照"""
    print("\n" + "=" * 70)
    print("測試 ETF 代碼對照")
    print("=" * 70)
    
    scraper = NomuraScraper()
    
    # 測試對照
    fund_id = scraper.get_fund_id('00980A')
    print(f"00980A -> {fund_id}")
    assert fund_id == '00980A', "ETF 代碼對照錯誤！"
    
    # 顯示所有對照
    print("\n所有 ETF 對照:")
    for etf, fund in scraper.get_all_mappings().items():
        print(f"  {etf} -> {fund}")
    
    print("✅ ETF 代碼對照測試通過")

def test_get_holdings():
    """測試抓取 00980A 持股明細"""
    print("\n" + "=" * 70)
    print("測試抓取 00980A 持股明細")
    print("=" * 70)
    
    scraper = NomuraScraper()
    
    # 使用昨天的日期（資料可能會有延遲）
    from datetime import timedelta
    test_date = datetime.now() - timedelta(days=1)
    
    # 如果是週末，往回推到週五
    while test_date.weekday() >= 5:
        test_date -= timedelta(days=1)
    
    date_str = test_date.strftime('%Y-%m-%d')
    print(f"抓取日期: {date_str} ({['週一', '週二', '週三', '週四', '週五', '週六', '週日'][test_date.weekday()]})")
    
    # 抓取持股資料
    holdings = scraper.get_etf_holdings('00980A', date_str)
    
    if not holdings:
        print("❌ 未能抓取到持股資料")
        print("\n可能原因:")
        print("  1. 該日期不是交易日")
        print("  2. API 尚未提供該日期的數據")
        print("  3. 網路連線問題")
        print("\n建議：嘗試使用更早的日期")
        return
    
    print(f"\n✅ 成功抓取到 {len(holdings)} 筆持股資料")
    print("\n前 10 大持股:")
    print("-" * 70)
    print(f"{'股票代號':<10} {'股票名稱':<20} {'持股數':<15} {'權重(%)':<10}")
    print("-" * 70)
    
    for i, holding in enumerate(holdings[:10], 1):
        print(f"{holding['stock_code']:<10} "
              f"{holding['stock_name']:<20} "
              f"{holding['shares']:>15,} "
              f"{holding['weight']:>9.2f}")
    
    if len(holdings) > 10:
        print(f"... 還有 {len(holdings) - 10} 筆資料")
    
    return holdings

def test_save_to_database(holdings):
    """測試儲存到資料庫"""
    print("\n" + "=" * 70)
    print("測試儲存到資料庫")
    print("=" * 70)
    
    if not holdings:
        print("⚠️ 沒有持股資料可儲存")
        return
    
    try:
        db = Database(DB_FULL_PATH)
        
        # 首先確保 ETF 存在於 etf_list 表中
        db.insert_etf_list([{
            'etf_code': '00980A',
            'etf_name': '野村台灣創新科技50',
            'issuer': '野村投信',
            'listing_date': ''
        }])
        
        # 儲存持股資料
        inserted = db.insert_holdings(holdings)
        print(f"✅ 成功儲存 {inserted} 筆新的持股資料到資料庫")
        
        # 查詢驗證
        latest_date = db.get_latest_date('00980A')
        print(f"資料庫中 00980A 的最新日期: {latest_date}")
        
        # 顯示統計
        stats = db.get_statistics()
        print(f"\n資料庫統計:")
        print(f"  總 ETF 數量: {stats['total_etfs']}")
        print(f"  總持股記錄: {stats['total_holdings']}")
        print(f"  日期範圍: {stats['date_range']['start']} ~ {stats['date_range']['end']}")
        
    except Exception as e:
        logger.error(f"資料庫操作失敗: {e}")
        logger.exception(e)

def main():
    """主測試程式"""
    print("\n" + "=" * 70)
    print("野村投信 ETF 爬蟲測試程式")
    print("=" * 70)
    
    try:
        # 1. 測試 ETF 對照
        test_etf_mapping()
        
        # 2. 測試抓取持股
        holdings = test_get_holdings()
        
        # 3. 測試儲存到資料庫（可選）
        if holdings:
            save = input("\n是否要將資料儲存到資料庫？(y/n): ").lower().strip()
            if save == 'y':
                test_save_to_database(holdings)
        
        print("\n" + "=" * 70)
        print("所有測試完成！")
        print("=" * 70)
    
    except KeyboardInterrupt:
        print("\n\n測試被使用者中斷")
    except Exception as e:
        logger.error(f"測試過程發生錯誤: {e}")
        logger.exception(e)

if __name__ == "__main__":
    main()
