"""
Check date behavior for FSITC and Nomura scrapers
"""
from datetime import datetime
from src.fsitc_scraper import FSITCScraper
from src.nomura_scraper import NomuraScraper

output_file = "check_results.txt"

with open(output_file, "w", encoding="utf-8") as f:
    f.write("=== Testing FSITC (00994A) ===\n")
    fsitc = FSITCScraper()
    for date in ['2026-01-26', '2026-01-27', '2026-01-28']:
        f.write(f"\nChecking FSITC for date: {date}\n")
        holdings = fsitc.get_etf_holdings('00994A', date)
        if holdings:
            f.write(f"  Found {len(holdings)} holdings\n")
            f.write(f"  Sample: {holdings[0]['stock_name']} {holdings[0]['shares']} shares\n")
        else:
            f.write("  No holdings found\n")

    f.write("\n\n=== Testing Nomura (00985A) ===\n")
    nomura = NomuraScraper()
    for date in ['2026-01-26', '2026-01-27', '2026-01-28']:
        f.write(f"\nChecking Nomura for date: {date}\n")
        holdings = nomura.get_etf_holdings('00985A', date)
        if holdings:
            f.write(f"  Found {len(holdings)} holdings\n")
            f.write(f"  Sample: {holdings[0]['stock_name']} {holdings[0]['shares']} shares\n")
        else:
            f.write("  No holdings found\n")
