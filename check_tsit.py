"""
Check date behavior for TSIT scraper
"""
from src.tsit_scraper import TSITScraper
import urllib3
urllib3.disable_warnings()

output_file = "check_tsit_results.txt"

with open(output_file, "w", encoding="utf-8") as f:
    f.write("=== Testing TSIT (00987A) ===\n")
    tsit = TSITScraper()
    for date in ['2026-01-26', '2026-01-27', '2026-01-28']:
        f.write(f"\nChecking TSIT for date: {date}\n")
        try:
            holdings = tsit.get_etf_holdings('00987A', date)
            if holdings:
                f.write(f"  Found {len(holdings)} holdings\n")
                f.write(f"  Sample: {holdings[0]['stock_name']} {holdings[0]['shares']} shares\n")
            else:
                f.write("  No holdings found\n")
        except Exception as e:
            f.write(f"  Error: {e}\n")
