"""
復華投信 ETF 爬蟲測試程式
"""
from src.fhtrust_scraper import FHTrustScraper
from src.database import Database
from src.config import DB_FULL_PATH
from datetime import datetime, timedelta


def test_etf_mapping():
    """測試 ETF 代碼對照"""
    print("=" * 70)
    print("測試 ETF 代碼對照")
    print("=" * 70)
    
    scraper = FHTrustScraper()
    
    # 測試取得fund_id
    fund_id = scraper.get_fund_id('00991A')
    print(f"00991A -> {fund_id}")
    
    # 顯示所有對照
    all_mappings = scraper.get_all_mappings()
    print(f"\n所有 ETF 對照:")
    for etf_code, fund_id in all_mappings.items():
        print(f"  {etf_code} -> {fund_id}")
    
    assert fund_id == 'ETF23', "ETF 代碼對照錯誤"
    print("✅ ETF 代碼對照測試通過")
    return True


def test_get_holdings():
    """測試抓取持股明細"""
    print("\n" + "=" * 70)
    print("測試抓取 00991A 持股明細（API 下載）")
    print("=" * 70)
    
    scraper = FHTrustScraper()
    
    # 使用昨天的日期
    yesterday = datetime.now() - timedelta(days=1)
    # 避免週末
    while yesterday.weekday() >= 5:
        yesterday -= timedelta(days=1)
    
    date_str = yesterday.strftime('%Y-%m-%d')
    print(f"抓取日期: {date_str} (週{['一','二','三','四','五','六','日'][yesterday.weekday()]})")
    
    # 抓取持股
    holdings = scraper.get_etf_holdings('00991A', date_str)
    
    if holdings:
        print(f"\n✅ 成功抓取到 {len(holdings)} 筆持股資料")
        
        print("\n前 10 大持股:")
        print("-" * 70)
        print(f"{'股票代號':<10} {'股票名稱':<20} {'持股數':>15} {'權重(%)':>10}")
        print("-" * 70)
        for holding in holdings[:10]:
            print(f"{holding['stock_code']:<10} {holding['stock_name']:<20} {holding['shares']:>15,} {holding['weight']:>10.2f}")
        
        if len(holdings) > 10:
            print(f"... 還有 {len(holdings) - 10} 筆資料")
        
        return holdings
    else:
        print("\n❌ 未能抓取到持股資料")
        print("\n可能原因:")
        print("  1. API 端點已變更")
        print("  2. 網路連線問題")
        print("  3. Excel 格式已變更")
        return None


def test_database_insert(holdings):
    """測試資料庫儲存"""
    if not holdings:
        print("\n跳過資料庫測試（無持股資料）")
        return False
    
    response = input("\n是否要將資料儲存到資料庫？(y/n): ")
    if response.lower() != 'y':
        print("跳過資料庫儲存")
        return False
    
    print("\n" + "=" * 70)
    print("測試資料庫儲存")
    print("=" * 70)
    
    db = Database(DB_FULL_PATH)
    
    # 插入 ETF 基本資料
    etf_info = [{
        'etf_code': '00991A',
        'etf_name': '復華台灣未來50主動式ETF基金',
        'issuer': '復華投信',
        'listing_date': ''
    }]
    
    db.insert_etf_list(etf_info)
    
    # 插入持股資料
    new_count = db.insert_holdings(holdings)
    
    print(f"✅ 成功儲存 {new_count} 筆新的持股資料到資料庫")
    
    # 查詢資料庫確認
    stats = db.get_statistics()
    print(f"\n資料庫統計:")
    print(f"  總 ETF 數量: {stats['total_etfs']}")
    print(f"  總持股記錄: {stats['total_holdings']}")
    print(f"  日期範圍: {stats['date_range']['start']} ~ {stats['date_range']['end']}")
    
    return True


def main():
    """主測試流程"""
    print("\n" + "=" * 70)
    print("復華投信 ETF 爬蟲測試程式")
    print("=" * 70)
    
    try:
        # 測試 1: ETF 代碼對照
        test_etf_mapping()
        
        # 測試 2: 抓取持股
        holdings = test_get_holdings()
        
        # 測試 3: 資料庫儲存
        if holdings:
            test_database_insert(holdings)
        
        print("\n" + "=" * 70)
        print("所有測試完成！")
        print("=" * 70)
    
    except Exception as e:
        print(f"\n❌ 測試失敗: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
