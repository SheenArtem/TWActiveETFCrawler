"""
測試中信投信 ETF 爬蟲
"""
from src.ctbc_scraper import CTBCScraper
from src.database import Database
from src.config import DB_FULL_PATH
from datetime import datetime, timedelta


def test_etf_mapping():
    """測試 ETF 代碼對照"""
    print("=" * 70)
    print("測試 ETF 代碼對照")
    print("=" * 70)
    
    scraper = CTBCScraper()
    
    # 測試取得fund_id
    fund_id = scraper.get_fund_id('00995A')
    print(f"00995A -> {fund_id}")
    
    # 顯示所有對照
    all_mappings = scraper.get_all_mappings()
    print(f"\n所有 ETF 對照:")
    for etf_code, fund_id in all_mappings.items():
        print(f"  {etf_code} -> {fund_id}")
    
    assert fund_id == '00653201', "ETF 代碼對照錯誤"
    print("✅ ETF 代碼對照測試通過")
    return True


def test_get_holdings():
    """測試抓取持股明細"""
    print("\n" + "=" * 70)
    print("測試抓取 00995A 持股明細（Playwright DOM 提取）")
    print("=" * 70)
    
    scraper = CTBCScraper()
    
    # 使用昨天的日期
    yesterday = datetime.now() - timedelta(days=1)
    # 避免週末
    while yesterday.weekday() >= 5:
        yesterday -= timedelta(days=1)
    
    date_str = yesterday.strftime('%Y-%m-%d')
    print(f"抓取日期: {date_str} (週{['一','二','三','四','五','六','日'][yesterday.weekday()]})")
    print("\n注意：此方法會啟動瀏覽器並點擊「看更多」按鈕...")
    
    # 抓取持股
    holdings = scraper.get_etf_holdings('00995A', date_str)
    
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
        print("  1. 網頁結構已變更")
        print("  2. 「看更多」按鈕選擇器不正確")
        print("  3. div 解析邏輯需調整")
        return None


def test_database_insert(holdings):
    if not holdings: return False
    
    response = input("\n是否要將資料儲存到資料庫？(y/n): ")
    if response.lower() != 'y': return False
    
    print("\n" + "=" * 70)
    print("測試資料庫儲存")
    print("=" * 70)
    
    db = Database(DB_FULL_PATH)
    
    etf_info = [{
        'etf_code': '00995A',
        'etf_name': '中國信託台灣卓越成長主動式ETF基金',
        'issuer': '中信投信',
        'listing_date': ''
    }]
    
    db.insert_etf_list(etf_info)
    new_count = db.insert_holdings(holdings)
    
    print(f"✅ 成功儲存 {new_count} 筆新的持股資料到資料庫")
    
    stats = db.get_statistics()
    print(f"\n資料庫統計:")
    print(f"  總 ETF 數量: {stats['total_etfs']}")
    print(f"  總持股記錄: {stats['total_holdings']}")
    
    return True


def main():
    print("\n" + "=" * 70)
    print("中信投信 ETF 爬蟲測試程式")
    print("=" * 70)
    
    try:
        test_etf_mapping()
        holdings = test_get_holdings()
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
