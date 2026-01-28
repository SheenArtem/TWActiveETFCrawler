"""
Quick test to verify the new EZMoney update logic
"""
import sys
import sqlite3

# First, delete today's data to test fresh insert
conn = sqlite3.connect('data/etf_holdings.db')
cursor = conn.cursor()
cursor.execute("DELETE FROM holdings WHERE etf_code='00981A' AND date='2026-01-27'")
deleted = cursor.rowcount
conn.commit()
conn.close()

print(f"Deleted {deleted} existing records for 00981A on 2026-01-27")
print("Now run: python main.py --ezmoney")
print("\nExpected results:")
print("  3653 健策: 898張 (was 767張, +131張)")
print("  2313 華通: 1473張 (was 5013張, -3540張)")
print("  5269 祥碩: 172張 (was 262張, -90張)")
