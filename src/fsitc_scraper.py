
import requests
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Optional
from loguru import logger
from src.utils import get_user_agent
import time
import random

class FSITCScraper:
    """第一金投信 (FSITC) 爬蟲"""
    
    BASE_URL = "https://www.fsitc.com.tw"
    API_URL = "https://www.fsitc.com.tw/WebAPI.aspx/Get_hd"
    
    # 基金代碼映射 (Fund ID -> ETF Code)
    # 目前已知 00994A -> 182
    FUND_ID_MAP = {
        "00994A": "182"
    }
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': get_user_agent(),
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': 'https://www.fsitc.com.tw',
            'Referer': 'https://www.fsitc.com.tw/FundDetail.aspx'
        })

    def get_etf_holdings(self, etf_code: str, date: str) -> tuple[List[Dict[str, Any]], str]:
        """
        獲取 ETF 持股明細
        
        Args:
            etf_code: ETF 代碼 (例如: 00994A)
            date: 日期 (YYYY-MM-DD)
            
        Returns:
            tuple: (持股明細列表, 實際數據日期)
        """
        fund_id = self.FUND_ID_MAP.get(etf_code)
        if not fund_id:
            logger.error(f"Unknown ETF code for FSITC: {etf_code}")
            return [], date
            
        holdings = []
        actual_date = date  # 默認使用請求日期
        try:
            # 準備請求數據
            payload = {
                "pStrFundID": fund_id,
                "pStrDate": date
            }
            
            logger.info(f"Fetching FSITC holdings for {etf_code} (ID: {fund_id}) on {date}")
            # Disable SSL verification due to certificate errors
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            response = self.session.post(self.API_URL, json=payload, timeout=10, verify=False)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                except Exception as e:
                    logger.error(f"Failed to parse JSON: {response.text[:200]}")
                    return [], date
                
                # 預期返回 {"d": "JSON string or HTML"} 或者直接是 JSON 結構
                result = data.get('d')
                
                if result is None:
                    # 如果沒有 d，嘗試直接使用 data (可能是 list 或其他結構)
                    # 檢查 data 是否為 list
                    if isinstance(data, list):
                        result = data
                    else:
                        logger.warning(f"Unexpected JSON structure: {data.keys() if isinstance(data, dict) else type(data)}")
                        return [], date
                
                # 如果 "d" 是 JSON 字串，需要再次解析
                import json
                if isinstance(result, str):
                    try:
                        # 嘗試解析 d 內容
                        if result.strip().startswith('<'): # HTML
                            holdings = self._parse_html_table(result, date)
                            # HTML格式無法提取實際日期，使用請求日期
                        else:
                            try:
                                inner_data = json.loads(result)
                                holdings, actual_date = self._parse_json_data(inner_data, date, etf_code)
                            except json.JSONDecodeError:
                                # 嘗試直接當作 HTML
                                holdings = self._parse_html_table(result, date, etf_code)
                                
                    except Exception as parse_e:
                        logger.error(f"Error parsing content: {parse_e}")
                else:
                    # 已經是 dict/list
                    holdings, actual_date = self._parse_json_data(result, date, etf_code)

                logger.info(f"Parsed {len(holdings)} holdings for {etf_code} (actual date: {actual_date})")
                
            else:
                logger.error(f"Failed to fetch data: HTTP {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error fetching FSITC holdings: {e}")
            logger.exception(e)
            
        return holdings, actual_date
    
    def _parse_html_table(self, html_content: str, date: str, etf_code: str = None) -> List[Dict[str, Any]]:
        """解析 HTML 表格數據"""
        from bs4 import BeautifulSoup
        
        holdings = []
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            # 尋找表格行
            # 根據 explore，可能結構是 li > span
            rows = soup.find_all('li')
            
            for row in rows:
                spans = row.find_all('span')
                # 預期欄位: 股票代碼, 股票名稱, 持股權重, 股數
                # 需確認 span 順序
                # 通常：Code, Name, Weight, Shares
                
                if len(spans) >= 4:
                    try:
                        # 假設順序，需測試驗證
                        # span[0]: 代碼
                        # span[1]: 名稱
                        # span[2]: 權重
                        # span[3]: 股數
                        
                        code = spans[0].text.strip()
                        name = spans[1].text.strip()
                        weight_str = spans[2].text.strip().replace('%', '')
                        shares_str = spans[3].text.strip().replace(',', '')
                        
                        # 簡單驗證
                        if code.isdigit() and len(code) == 4:
                            holdings.append({
                                'etf_code': etf_code,
                                'stock_code': code,
                                'stock_name': name,
                                'shares': int(float(shares_str)) if shares_str else 0,
                                'weight': float(weight_str) if weight_str else 0.0,
                                'market_value': 0,
                                'date': date
                            })
                    except Exception as e:
                        logger.debug(f"Error parsing row: {e}")
                        continue
                        
        except Exception as e:
            logger.error(f"Error parsing HTML: {e}")
            
        return holdings

    def _parse_json_data(self, data: List[Dict], date: str, etf_code: str = None) -> tuple[List[Dict[str, Any]], str]:
        """解析 JSON 列表數據"""
        holdings = []
        # JSON keys mapping found:
        # A: StockCode
        # B: StockName
        # C: Weight (%)
        # D: Shares (with commas)
        # sdate: 實際數據日期 (YYYY-MM-DD)
        
        # 嘗試從第一筆數據中提取實際日期
        actual_date = date  # 默認使用傳入的日期
        if data and len(data) > 0:
            first_item = data[0]
            if 'sdate' in first_item and first_item['sdate']:
                actual_date = first_item['sdate']
                logger.info(f"Using actual date from API: {actual_date} (requested: {date})")
        
        for item in data:
            try:
                # 嘗試多種可能的 key
                code = item.get('A') or item.get('StockCode') or item.get('Code')
                name = item.get('B') or item.get('StockName') or item.get('Name')
                weight_val = item.get('C') or item.get('Rate') or item.get('Weight')
                shares_val = item.get('D') or item.get('Sheets') or item.get('Shares')
                
                if code:
                    # 處理數據格式
                    shares = 0
                    if shares_val:
                        shares_str = str(shares_val).replace(',', '').strip()
                        if shares_str.replace('.', '').isdigit():
                            shares = int(float(shares_str))
                            
                    weight = 0.0
                    if weight_val:
                        weight_str = str(weight_val).replace('%', '').strip()
                        try:
                            weight = float(weight_str)
                        except ValueError:
                            pass
                            
                    holdings.append({
                        'etf_code': etf_code,
                        'stock_code': str(code).strip(),
                        'stock_name': str(name).strip(),
                        'shares': shares,
                        'weight': weight,
                        'market_value': 0,
                        'date': actual_date  # 使用從API提取的實際日期
                    })
            except Exception as e:
                logger.warning(f"Error parsing JSON item: {e}")
                
        return holdings, actual_date  # 返回holdings和實際使用的日期

    def get_all_mappings(self) -> Dict[str, str]:
        """獲取所有支持的 ETF 代碼映射"""
        return self.FUND_ID_MAP
