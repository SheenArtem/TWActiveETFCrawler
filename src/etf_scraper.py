"""
ETF 爬蟲模組
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import time
import random
from typing import List, Dict, Any, Optional
from datetime import datetime
from fake_useragent import UserAgent
from loguru import logger

from .config import (
    TWSE_ETF_LIST_URL,
    TWSE_ETF_HOLDINGS_URL,
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX,
    BATCH_DELAY_MIN,
    BATCH_DELAY_MAX,
    MAX_RETRIES
)
from .utils import is_active_etf


class ETFScraper:
    """台灣證交所 ETF 爬蟲"""
    
    def __init__(self):
        """初始化爬蟲"""
        self.ua = UserAgent()
        self.session = self._create_session()
        self.request_count = 0
    
    def _create_session(self) -> requests.Session:
        """
        建立 HTTP Session 並設定重試策略
        
        Returns:
            requests.Session: 配置好的 session
        """
        session = requests.Session()
        
        # 設定重試策略
        retry_strategy = Retry(
            total=MAX_RETRIES,
            backoff_factor=1,  # 指數退避：1, 2, 4 秒
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def _get_headers(self) -> Dict[str, str]:
        """
        獲取隨機 User-Agent 的請求標頭
        
        Returns:
            Dict: HTTP Headers
        """
        return {
            'User-Agent': self.ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
    
    def _random_delay(self):
        """隨機延遲，避免被封鎖"""
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        logger.debug(f"Waiting {delay:.2f} seconds...")
        time.sleep(delay)
    
    def _batch_delay(self):
        """批次處理延遲（每10筆請求）"""
        if self.request_count > 0 and self.request_count % 10 == 0:
            delay = random.uniform(BATCH_DELAY_MIN, BATCH_DELAY_MAX)
            logger.info(f"Batch delay: waiting {delay:.2f} seconds after {self.request_count} requests")
            time.sleep(delay)
    
    def _make_request(self, url: str, params: Optional[Dict] = None) -> Optional[requests.Response]:
        """
        發送 HTTP 請求（含重試和延遲機制）
        
        Args:
            url: 請求 URL
            params: 查詢參數
        
        Returns:
            requests.Response 或 None（失敗時）
        """
        self._random_delay()
        self.request_count += 1
        self._batch_delay()
        
        try:
            response = self.session.get(
                url,
                params=params,
                headers=self._get_headers(),
                timeout=30
            )
            response.raise_for_status()
            logger.debug(f"Request successful: {url}")
            return response
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {url} - {e}")
            return None
    
    def get_active_etf_list(self) -> List[Dict[str, Any]]:
        """
        取得所有主動式 ETF 清單（股票代碼 A 結尾）
        
        Returns:
            List[Dict]: ETF 清單
        """
        logger.info("Fetching active ETF list...")
        
        response = self._make_request(TWSE_ETF_LIST_URL)
        if not response:
            logger.error("Failed to fetch ETF list")
            return []
        
        # 解析 HTML
        soup = BeautifulSoup(response.text, 'lxml')
        
        # 尋找 ETF 表格（根據台灣證交所網站結構調整）
        # 注意：實際網站結構可能需要調整選擇器
        etf_list = []
        
        # 方法 1：嘗試尋找包含 ETF 資訊的表格
        tables = soup.find_all('table')
        
        for table in tables:
            rows = table.find_all('tr')
            for row in rows[1:]:  # 跳過標題列
                cols = row.find_all(['td', 'th'])
                if len(cols) >= 2:
                    # 假設第一欄是代碼，第二欄是名稱
                    etf_code = cols[0].get_text(strip=True)
                    etf_name = cols[1].get_text(strip=True)
                    
                    # 只選擇主動式 ETF（A 結尾）
                    if is_active_etf(etf_code):
                        etf_list.append({
                            'etf_code': etf_code,
                            'etf_name': etf_name,
                            'issuer': cols[2].get_text(strip=True) if len(cols) > 2 else '',
                            'listing_date': cols[3].get_text(strip=True) if len(cols) > 3 else ''
                        })
        
        # 如果上面的方法沒找到，嘗試從 JSON API（如果有的話）
        if not etf_list:
            logger.warning("No ETFs found in HTML, trying alternative method...")
            # TODO: 實作從 JSON API 取得資料的方法
        
        logger.info(f"Found {len(etf_list)} active ETFs")
        return etf_list
    
    def get_etf_holdings(self, etf_code: str, date: str) -> List[Dict[str, Any]]:
        """
        取得指定 ETF 在特定日期的持股明細
        
        Args:
            etf_code: ETF 代碼
            date: 日期 (YYYY-MM-DD 或 YYYYMMDD)
        
        Returns:
            List[Dict]: 持股明細
        """
        # 轉換日期格式為 YYYYMMDD（證交所 API 格式）
        if '-' in date:
            date = date.replace('-', '')
        
        logger.info(f"Fetching holdings for {etf_code} on {date}")
        
        params = {
            'response': 'json',
            'date': date,
            's tockNo': etf_code  # 注意：實際參數名稱需要根據證交所 API 調整
        }
        
        response = self._make_request(TWSE_ETF_HOLDINGS_URL, params=params)
        if not response:
            logger.error(f"Failed to fetch holdings for {etf_code} on {date}")
            return []
        
        holdings = []
        
        try:
            # 嘗試解析 JSON 回應
            data = response.json()
            
            # 根據實際的 JSON 結構解析（需要根據證交所 API 調整）
            if 'data' in data:
                for item in data['data']:
                    holdings.append({
                        'etf_code': etf_code,
                        'stock_code': item[0],  # 股票代碼
                        'stock_name': item[1],  # 股票名稱
                        'shares': int(item[2].replace(',', '')) if item[2] else 0,  # 持股數
                        'market_value': float(item[3].replace(',', '')) if item[3] else 0.0,  # 市值
                        'weight': float(item[4].replace('%', '')) if item[4] else 0.0,  # 權重
                        'date': f"{date[:4]}-{date[4:6]}-{date[6:8]}"  # 轉回 YYYY-MM-DD
                    })
        
        except Exception as e:
            logger.error(f"Error parsing holdings data: {e}")
            # 如果 JSON 解析失敗，嘗試 HTML 解析
            soup = BeautifulSoup(response.text, 'lxml')
            # TODO: 實作 HTML 解析邏輯
        
        logger.info(f"Found {len(holdings)} holdings for {etf_code} on {date}")
        return holdings
    
    def get_historical_holdings(
        self, 
        etf_code: str, 
        start_date: str, 
        end_date: str,
        trading_days: List[datetime]
    ) -> List[Dict[str, Any]]:
        """
        批次取得 ETF 的歷史持股資料
        
        Args:
            etf_code: ETF 代碼
            start_date: 開始日期 (YYYY-MM-DD)
            end_date: 結束日期 (YYYY-MM-DD)
            trading_days: 交易日列表
        
        Returns:
            List[Dict]: 所有持股明細
        """
        logger.info(f"Fetching historical holdings for {etf_code} from {start_date} to {end_date}")
        
        all_holdings = []
        
        for trading_day in trading_days:
            date_str = trading_day.strftime('%Y-%m-%d')
            holdings = self.get_etf_holdings(etf_code, date_str)
            all_holdings.extend(holdings)
            
            # 避免過於頻繁的請求
            if len(all_holdings) % 50 == 0:
                logger.info(f"Progress: {len(all_holdings)} holdings fetched for {etf_code}")
        
        logger.info(f"Total {len(all_holdings)} holdings fetched for {etf_code}")
        return all_holdings
