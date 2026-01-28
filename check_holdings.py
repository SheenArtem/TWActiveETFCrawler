import sqlite3
from datetime import datetime

conn = sqlite3.connect('data/etf_holdings.db')
cursor = conn.cursor()

# 查詢所有日期的資料
cursor.execute('''
    SELECT DISTINCT date FROM holdings 
    WHERE etf_code='00981A' 
    ORDER BY date DESC
''')
dates = cursor.fetchall()
print("Available dates for 00981A:")
for date in dates:
    print(f"  {date[0]}")

# 查詢最近兩天的特定股票資料
stocks = ['3653', '2313', '5269']
print("\nData for stocks 3653, 2313, 5269:")

for stock in stocks:
    print(f"\n{stock}:")
    cursor.execute('''
        SELECT date, stock_name, shares 
        FROM holdings 
        WHERE etf_code='00981A' AND stock_code=?
        ORDER BY date DESC 
        LIMIT 5
    ''', (stock,))
    rows = cursor.fetchall()
    for row in rows:
        lots = row[2] / 1000
        print(f"  {row[0]}: {row[1]} - {row[2]} shares ({lots:.2f} lots)")

conn.close()
