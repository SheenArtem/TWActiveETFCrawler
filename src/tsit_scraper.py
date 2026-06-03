
import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Optional
from loguru import logger
from src.utils import get_user_agent
import time
import random

class TSITScraper:
    """台新投信 (TSIT) 爬蟲"""
    
    BASE_URL = "https://www.tsit.com.tw"
    PCF_URL = "https://www.tsit.com.tw/ETF/Home/Pcf/{etf_code}"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': get_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        })

    def get_etf_holdings(self, etf_code: str, date: str) -> List[Dict[str, Any]]:
        """
        獲取 ETF 持股明細
        
        Args:
            etf_code: ETF 代碼 (例如: 00987A)
            date: 日期 (YYYY-MM-DD)
            
        Returns:
            List[Dict]: 持股明細列表
        """
        holdings = []
        try:
            url = self.PCF_URL.format(etf_code=etf_code)
            logger.info(f"Fetching TSIT holdings for {etf_code} from {url}")
            
            # 台新投信的頁面是 SSR，但日期查詢是 POST 表單
            # 如果是獲取最新日期的資料，直接 GET 即可
            # 如果需要指定日期，可能需要分析 Form Data (ViewState 等)
            
            # 目前策略：先嘗試 GET 獲取預設頁面 (通常是最新交易日)
            # 如果需要指定日期，這會比較複雜 (因為 ASP.NET 通常有大量隱藏欄位)
            # 觀察 browser_subagent，日期選擇器是 #PUB_DATE
            
            # Disable SSL verification
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            response = self.session.get(url, timeout=10, verify=False)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 檢查這是否是我們想要的日期
                # 日期通常顯示在 #PUB_DATE 的 value 或頁面上某處
                page_date_input = soup.select_one('#PUB_DATE')
                page_date = page_date_input.get('value') if page_date_input else None
                
                if page_date:
                    logger.info(f"Page date: {page_date}")
                    # 簡單檢查：如果請求的 date 和頁面 date 差距過大，可能需要 POST
                    pass
                
                holdings = self._parse_html_table(soup, date, etf_code)
                logger.info(f"Parsed {len(holdings)} holdings for {etf_code}")
                
            else:
                logger.error(f"Failed to fetch data: HTTP {response.status_code}")
                
        except Exception as e:
            logger.error(f"Error fetching TSIT holdings: {e}")
            logger.exception(e)
            
        return holdings
    
    def _parse_html_table(self, soup: BeautifulSoup, date: str, etf_code: str = None) -> List[Dict[str, Any]]:
        """解析 HTML 表格數據"""
        holdings = []
        try:
            # 定位持股表格：表頭同時含「股數」與「權重」即為股票持股表。
            # 台新 2026 改版後已移除 panel-heading 結構，改以表頭欄位辨識；
            # 期貨表用「口數」、資產彙總表無這些欄位，可藉此排除。
            table = None
            for t in soup.find_all('table'):
                header_text = ' '.join(th.get_text(strip=True) for th in t.find_all('th'))
                if '股數' in header_text and '權重' in header_text and '口數' not in header_text:
                    table = t
                    break

            if not table:
                logger.warning(f"TSIT: stock holdings table not found for {etf_code} (page structure changed?)")
                return []

            # 解析表格
            # 預期欄位: 代號, 名稱, 股數, 持股權重
            # Ticker, Name, Shares, Weight

            rows = table.find_all('tr')
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    try:
                        # 0: 代號 (可能包含 TT)
                        code_text = cols[0].text.strip()
                        code = code_text.split(' ')[0] # 去除 ' TT'
                        
                        # 1: 名稱
                        name = cols[1].text.strip()
                        
                        # 2: 股數 (有逗號)
                        shares_text = cols[2].text.strip().replace(',', '')
                        shares = int(float(shares_text)) if shares_text else 0
                        
                        # 3: 權重 (有 %)
                        weight_text = cols[3].text.strip().replace('%', '')
                        weight = float(weight_text) if weight_text else 0.0
                        
                        # 忽略總計行 (代號為空或名稱為合計)
                        if not code or "合計" in name:
                            continue
                            
                        # 簡單驗證代碼格式 (4碼數字)
                        if code.isdigit() and len(code) == 4:
                            holdings.append({
                                'etf_code': etf_code,  # 添加 etf_code
                                'stock_code': code,
                                'stock_name': name,
                                'shares': shares,
                                'weight': weight,
                                'market_value': 0,  # 台新投信網站沒有提供市值
                                'date': date # 這裡使用傳入的 date
                            })
                    except Exception as e:
                        logger.debug(f"Error parsing row: {e}")
                        continue
                        
        except Exception as e:
            logger.error(f"Error parsing HTML: {e}")
            
        return holdings

    def get_all_mappings(self) -> Dict[str, str]:
        """獲取所有支持的 ETF 代碼"""
        # 00987A 是已知的
        return {
            "00987A": "00987A"
        }
