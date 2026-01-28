"""
Test script to directly call EZMoney scraper and see what data it returns
"""
from datetime import datetime
from src.ezmoney_scraper import EZMoneyScraper

scraper = EZMoneyScraper()

# Test for today
today = datetime.now()
date_str = today.strftime('%Y-%m-%d')
print(f"Testing scraper for date: {date_str}")

holdings = scraper.get_etf_holdings('00981A', date_str)

if holdings:
    print(f"\nFound {len(holdings)} holdings")
    
    # Show specific stocks
    stocks_to_check = ['3653', '2313', '5269']
    print("\nChecking specific stocks:")
    for holding in holdings:
        if holding['stock_code'] in stocks_to_check:
            lots = holding['shares'] / 1000
            print(f"  {holding['stock_code']} {holding['stock_name']}: {holding['shares']} shares ({lots:.2f} lots)")
else:
    print("No holdings retrieved!")
