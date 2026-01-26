"""
EZMoney ETF 爬蟲模組
專門處理 EZMoney 網站的 ETF PCF (申購買回清單) 資料抓取
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


# EZMoney ETF 基金代碼對照表
EZMONEY_ETF_CODES = {
    '00981A': '49YTW',  # 主動統一台股增長
    # 未來可以新增其他 ETF 的對照
}


class EZMoneyScraper:
    """EZMoney 網站 ETF 爬蟲"""
    
    API_URL = "https://www.ezmoney.com.tw/ETF/Transaction/GetPCF"
    
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
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            #  'Accept-Encoding': 'gzip, deflate, br',  # 移除以避免壓縮問題
            'Content-Type': 'application/json; charset=UTF-8',
            'Origin': 'https://www.ezmoney.com.tw',
            'Referer': 'https://www.ezmoney.com.tw/ETF/Transaction/PCF',
            'X-Requested-With': 'XMLHttpRequest'
        }
    
    def _random_delay(self):
        """隨機延遲，避免被封鎖"""
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        logger.debug(f"Waiting {delay:.2f} seconds...")
        time.sleep(delay)
    
    @staticmethod
    def _convert_to_roc_date(date_str: str) -> str:
        """
        將西元日期轉換為民國年格式
        
        Args:
            date_str: 西元日期 (YYYY-MM-DD)
        
        Returns:
            str: 民國年日期 (YYY/MM/DD)
        
        Examples:
            >>> _convert_to_roc_date('2025-01-26')
            '114/01/26'
        """
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        roc_year = dt.year - 1911
        return f"{roc_year}/{dt.month:02d}/{dt.day:02d}"
    
    @staticmethod
    def _convert_from_roc_date(roc_date_str: str) -> str:
        """
        將民國年格式轉換為西元日期
        
        Args:
            roc_date_str: 民國年日期 (YYY/MM/DD)
        
        Returns:
            str: 西元日期 (YYYY-MM-DD)
        
        Examples:
            >>> _convert_from_roc_date('114/01/26')
            '2025-01-26'
        """
        parts = roc_date_str.split('/')
        year = int(parts[0]) + 1911
        month = int(parts[1])
        day = int(parts[2])
        return f"{year}-{month:02d}-{day:02d}"
    
    def get_fund_code(self, etf_code: str) -> Optional[str]:
        """
        獲取 ETF 在 EZMoney 網站的基金代碼
        
        Args:
            etf_code: ETF 代碼 (例如: 00981A)
        
        Returns:
            Optional[str]: 基金代碼，若未找到則返回 None
        """
        fund_code = EZMONEY_ETF_CODES.get(etf_code)
        if not fund_code:
            logger.warning(f"ETF {etf_code} not found in EZMoney code mapping")
        return fund_code
    
    def get_pcf_data(
        self, 
        fund_code: str, 
        date: str,
        specific_date: bool = True  # 改為 True
    ) -> Optional[Dict[str, Any]]:
        """
        抓取 ETF 的 PCF (申購買回清單) 數據
        
        Args:
            fund_code: EZMoney 基金代碼 (例如: 49YTW)
            date: 日期 (YYYY-MM-DD)
            specific_date: 是否指定特定日期（預設為 True）
        
        Returns:
            Optional[Dict]: API 回應數據，失敗時返回 None
        """
        self._random_delay()
        self.request_count += 1
        
        # 轉換日期格式
        roc_date = self._convert_to_roc_date(date)
        
        # 準備請求數據
        payload = {
            "fundCode": fund_code,
            "date": roc_date,
            "specificDate": specific_date
        }
        
        logger.info(f"Fetching PCF data for {fund_code} on {date} (ROC: {roc_date})")
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
            logger.debug(f"Response preview: {response.text[:200]}")
            
            if not response.text:
                logger.error(f"Empty response received for {fund_code}")
                return None
            
            data = response.json()
            logger.debug(f"Request successful: {fund_code}")
            return data
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {fund_code} - {e}")
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
            etf_code: ETF 代碼 (例如: 00981A)
            date: 日期 (YYYY-MM-DD)
        
        Returns:
            List[Dict]: 持股明細列表
        """
        # 獲取基金代碼
        fund_code = self.get_fund_code(etf_code)
        if not fund_code:
            logger.error(f"Cannot fetch holdings: ETF {etf_code} not in mapping")
            return []
        
        # 抓取 PCF 數據
        data = self.get_pcf_data(fund_code, date)
        if not data:
            logger.error(f"Failed to fetch PCF data for {etf_code}")
            return []
        
        holdings = []
        
        try:
            # 解析 API 數據結構
            # 成分股在 asset 陣列中（直接在根層級，不在 data 下）
            asset_list = data.get('asset', [])
            
            logger.debug(f"Found {len(asset_list)} asset categories")
            
            if not asset_list:
                logger.warning(f"No asset data found for {etf_code} on {date}")
                return []
            
            # 找出股票類資產 (AssetCode: "ST")
            stock_asset = None
            for i, asset in enumerate(asset_list):
                asset_code = asset.get('AssetCode', '')
                asset_name = asset.get('AssetName', '')
                logger.debug(f"Asset {i}: {asset_code} - {asset_name}")
                
                if asset_code == 'ST':
                    stock_asset = asset
                    break
            
            if not stock_asset:
                logger.warning(f"No stock holdings found for {etf_code} on {date}")
                return []
            
            # 解析持股明細
            details = stock_asset.get('Details', [])
            logger.info(f"Found {len(details)} stock holdings")
            
            for item in details:
                holding = {
                    'etf_code': etf_code,
                    'stock_code': item.get('DetailCode', ''),
                    'stock_name': item.get('DetailName', ''),
                    'shares': self._parse_number(item.get('Share', 0)),
                    'market_value': self._parse_number(item.get('Amount', 0)),
                    'weight': self._parse_percentage(item.get('NavRate', 0)),
                    'date': date
                }
                holdings.append(holding)
            
            logger.info(f"Parsed {len(holdings)} holdings for {etf_code} on {date}")
        
        except Exception as e:
            logger.error(f"Error parsing PCF data: {e}")
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
            return int(value.replace(',', '').replace(' ', ''))
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
            return float(value.replace('%', '').replace(',', '').replace(' ', ''))
        return 0.0
    
    def add_etf_mapping(self, etf_code: str, fund_code: str):
        """
        新增 ETF 與 EZMoney 基金代碼的對照
        
        Args:
            etf_code: ETF 代碼 (例如: 00981A)
            fund_code: EZMoney 基金代碼 (例如: 49YTW)
        """
        EZMONEY_ETF_CODES[etf_code] = fund_code
        logger.info(f"Added ETF mapping: {etf_code} -> {fund_code}")
    
    def get_all_mappings(self) -> Dict[str, str]:
        """
        獲取所有 ETF 對照表
        
        Returns:
            Dict[str, str]: ETF 代碼對照字典
        """
        return EZMONEY_ETF_CODES.copy()
