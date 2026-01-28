"""
Test fetching with tomorrow's date (announcement date)
"""
from datetime import datetime, timedelta
from src.ezmoney_scraper import EZMoneyScraper

scraper = EZMoneyScraper()

# EZMoney的資料公告日期是T+1，所以1/27的資料在1/28公告
tomorrow = datetime.now() + timedelta(days=1)
date_str = tomorrow.strftime('%Y-%m-%d')

print(f"Testing with tomorrow's date: {date_str}")

holdings = scraper.get_etf_holdings('00981A', date_str)

if holdings:
    print(f"\nFound {len(holdings)} holdings")
    
    stocks_to_check = ['3653', '2313', '5269']
    print("\nChecking specific stocks:")
    for holding in holdings:
        if holding['stock_code'] in stocks_to_check:
            lots = holding['shares'] / 1000
            print(f"  {holding['stock_code']} {holding['stock_name']}: {holding['shares']} shares ({lots:.2f} lots)")
            
    # Also check what date the holdings are marked as
    if holdings:
        print(f"\nHoldings are marked with date: {holdings[0]['date']}")
else:
    print("No holdings retrieved!")
