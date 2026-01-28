"""
Check date behavior for FSITC and Nomura scrapers
"""
from datetime import datetime
from src.fsitc_scraper import FSITCScraper
from src.nomura_scraper import NomuraScraper

dates_to_check = ['2026-01-26', '2026-01-27', '2026-01-28']

print("=== Testing FSITC (00994A) ===")
fsitc = FSITCScraper()
for date in dates_to_check:
    print(f"\nChecking FSITC for date: {date}")
    holdings = fsitc.get_etf_holdings('00994A', date)
    if holdings:
        print(f"  Found {len(holdings)} holdings")
        print(f"  Sample: {holdings[0]['stock_name']} {holdings[0]['shares']} shares")
    else:
        print("  No holdings found")

print("\n\n=== Testing Nomura (00985A) ===")
nomura = NomuraScraper()
for date in dates_to_check:
    print(f"\nChecking Nomura for date: {date}")
    holdings = nomura.get_etf_holdings('00985A', date)
    if holdings:
        print(f"  Found {len(holdings)} holdings")
        print(f"  Sample: {holdings[0]['stock_name']} {holdings[0]['shares']} shares")
    else:
        print("  No holdings found")
