"""
Test with different date parameter
"""
from datetime import datetime, timedelta
from src.ezmoney_scraper import EZMoneyScraper

scraper = EZMoneyScraper()

# Try with specificDate = False
print("=== Testing with specificDate=False ===")
fund_code = '49YTW'
date_str = '2026-01-27'

data = scraper.get_pcf_data(fund_code, date_str, specific_date=False)

if data:
    print(f"Response received")
    # Check the date in response
    if 'pcf' in data and len(data['pcf']) > 0:
        pcf_date = data['pcf'][0].get('TranDate', 'N/A')
        print(f"PCF TranDate: {pcf_date}")
    
    holdings = scraper.get_etf_holdings('00981A', date_str)
    if holdings:
        print(f"\nFound {len(holdings)} holdings")
        stocks_to_check = ['3653', '2313', '5269']
        for holding in holdings:
            if holding['stock_code'] in stocks_to_check:
                lots = holding['shares'] / 1000
                print(f"  {holding['stock_code']} {holding['stock_name']}: {lots:.2f} lots")
else:
    print("No data returned")
