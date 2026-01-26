"""
檢查野村API回應結構
"""
import requests
import json
from datetime import datetime, timedelta
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

url = "https://www.nomurafunds.com.tw/API/ETFAPI/api/Fund/GetFundAssets"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Content-Type': 'application/json',
}

test_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
payload = {"FundID": "00980A", "SearchDate": test_date}

print(f"測試日期: {test_date}")
response = requests.post(url, json=payload, headers=headers, verify=False)

if response.status_code == 200:
    data = response.json()
    print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])  # 前2000字元
else:
    print(f"Error: {response.status_code}")
