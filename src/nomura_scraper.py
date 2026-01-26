"""
野村投信 ETF 爬蟲模組
專門處理野村投信網站的 ETF 資料抓取
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import random
from typing import List, Dict, Any, Optional
from datetime import datetime
from loguru import logger

from .config import (
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX,
    MAX_RETRIES
)


# 野村投信 ETF 基金代碼對照表
NOMURA_ETF_CODES = {
    '00980A': '00980A',  # 野村台灣創新科技50
    '00985A': '00985A',  # 主動野村台灣50
    # 未來可以新增其他野村 ETF
}


class NomuraScraper:
    """野村投信網站 ETF 爬蟲"""
    
    API_URL = "https://www.nomurafunds.com.tw/API/ETFAPI/api/Fund/GetFundAssets"
    
    def __init__(self):
        """初始化爬蟲"""
        self.session = self._create_session()
        self.request_count = 0
    
    def _create_session(self) -> requests.Session:
        """
        建立 HTTP Session 並設定重試策略
        
        Returns:
            requests.Session: 配置好的 session
        """
        session = requests.Session()
        
        # 禁用 SSL 驗證警告
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # 設定重試策略
        retry_strategy = Retry(
            total=MAX_RETRIES,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def _get_headers(self) -> Dict[str, str]:
        """
        獲取請求標頭
        
        Returns:
            Dict: HTTP Headers
        """
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Content-Type': 'application/json',
            'Origin': 'https://www.nomurafunds.com.tw',
            'Referer': 'https://www.nomurafunds.com.tw/ETFWEB/product-description'
        }
    
    def _random_delay(self):
        """隨機延遲，避免被封鎖"""
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        logger.debug(f"Waiting {delay:.2f} seconds...")
        time.sleep(delay)
    
    def get_fund_id(self, etf_code: str) -> Optional[str]:
        """
        獲取 ETF 在野村投信網站的基金代碼
        
        Args:
            etf_code: ETF 代碼 (例如: 00980A)
        
        Returns:
            Optional[str]: 基金代碼，若未找到則返回 None
        """
        fund_id = NOMURA_ETF_CODES.get(etf_code)
        if not fund_id:
            logger.warning(f"ETF {etf_code} not found in Nomura code mapping")
        return fund_id
    
    def get_fund_assets(
        self, 
        fund_id: str, 
        date: str
    ) -> Optional[Dict[str, Any]]:
        """
        抓取 ETF 的資產數據
        
        Args:
            fund_id: 野村投信基金代碼 (例如: 00980A)
            date: 日期 (YYYY-MM-DD)
        
        Returns:
            Optional[Dict]: API 回應數據，失敗時返回 None
        """
        self._random_delay()
        self.request_count += 1
        
        # API 接受 YYYY-MM-DD 格式，直接使用
        search_date = date
        
        # 準備請求數據
        payload = {
            "FundID": fund_id,
            "SearchDate": search_date
        }
        
        logger.info(f"Fetching fund assets for {fund_id} on {date}")
        logger.debug(f"Request payload: {payload}")
        
        try:
            response = self.session.post(
                self.API_URL,
                json=payload,
                headers=self._get_headers(),
                timeout=30,
                verify=False  # 禁用 SSL 驗證
            )
            response.raise_for_status()
            
            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response length: {len(response.text)} characters")
            
            if not response.text:
                logger.error(f"Empty response received for {fund_id}")
                return None
            
            data = response.json()
            logger.debug(f"Request successful: {fund_id}")
            return data
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {fund_id} - {e}")
            if 'response' in locals():
                logger.error(f"Response status: {response.status_code if response else 'N/A'}")
                logger.error(f"Response text: {response.text[:500] if response else 'N/A'}")
            return None
        except ValueError as e:
            logger.error(f"JSON parsing failed: {e}")
            if 'response' in locals():
                logger.error(f"Response text: {response.text[:500]}")
            return None
    
    def get_etf_holdings(
        self, 
        etf_code: str, 
        date: str
    ) -> List[Dict[str, Any]]:
        """
        獲取指定 ETF 在特定日期的持股明細
        
        Args:
            etf_code: ETF 代碼 (例如: 00980A)
            date: 日期 (YYYY-MM-DD)
        
        Returns:
            List[Dict]: 持股明細列表
        """
        # 獲取基金代碼
        fund_id = self.get_fund_id(etf_code)
        if not fund_id:
            logger.error(f"Cannot fetch holdings: ETF {etf_code} not in mapping")
            return []
        
        # 抓取資產數據
        data = self.get_fund_assets(fund_id, date)
        if not data:
            logger.error(f"Failed to fetch fund assets for {etf_code}")
            return []
        
        holdings = []
        
        try:
            # 解析 API 數據結構
            # 資料在 Entries.Data.Table 陣列中
            entries = data.get('Entries', {})
            table_data = entries.get('Data', {}).get('Table', [])
            
            if not table_data:
                logger.warning(f"No holdings data found for {etf_code} on {date}")
                return []
            
            logger.debug(f"Found {len(table_data)} table items")
            
            # 找出股票資產表（TableTitle 為「股票」）
            for table in table_data:
                table_title = table.get('TableTitle', '')
                
                # 只處理股票類資產
                if table_title == '股票':
                    rows = table.get('Rows', [])
                    logger.info(f"Found {len(rows)} stock holdings")
                    
                    # Rows 是二維陣列，每行格式: [股票代號, 股票名稱, 股數, 權重(%)]
                    for row in rows:
                        if len(row) >= 4:  # 確保有足夠的欄位
                            holding = {
                                'etf_code': etf_code,
                                'stock_code': row[0],
                                'stock_name': row[1],
                                'shares': self._parse_number(row[2]),
                                'market_value': 0,  # API 未提供市值
                                'weight': self._parse_percentage(row[3]),
                                'date': date
                            }
                            holdings.append(holding)
            
            logger.info(f"Parsed {len(holdings)} holdings for {etf_code} on {date}")
        
        except Exception as e:
            logger.error(f"Error parsing fund assets data: {e}")
            logger.exception(e)
        
        return holdings
    
    @staticmethod
    def _parse_number(value: Any) -> int:
        """
        解析數字（移除逗號等格式）
        
        Args:
            value: 原始數值
        
        Returns:
            int: 解析後的整數
        """
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            # 移除逗號和空格
            clean_value = value.replace(',', '').replace(' ', '').strip()
            return int(float(clean_value)) if clean_value else 0
        return 0
    
    @staticmethod
    def _parse_percentage(value: Any) -> float:
        """
        解析百分比（移除 % 符號）
        
        Args:
            value: 原始數值
        
        Returns:
            float: 解析後的浮點數
        """
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # 移除 % 和空格
            clean_value = value.replace('%', '').replace(',', '').replace(' ', '').strip()
            return float(clean_value) if clean_value else 0.0
        return 0.0
    
    def add_etf_mapping(self, etf_code: str, fund_id: str):
        """
        新增 ETF 與野村投信基金代碼的對照
        
        Args:
            etf_code: ETF 代碼 (例如: 00980A)
            fund_id: 野村投信基金代碼 (例如: 00980A)
        """
        NOMURA_ETF_CODES[etf_code] = fund_id
        logger.info(f"Added ETF mapping: {etf_code} -> {fund_id}")
    
    def get_all_mappings(self) -> Dict[str, str]:
        """
        獲取所有 ETF 對照表
        
        Returns:
            Dict[str, str]: ETF 代碼對照字典
        """
        return NOMURA_ETF_CODES.copy()
