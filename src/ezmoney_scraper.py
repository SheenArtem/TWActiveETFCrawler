"""
EZMoney ETF 爬蟲模組
專門處理 EZMoney 網站的 ETF 持股資料抓取
支援兩種方式：
1. Playwright 網頁下載 Excel (主要方式，更可靠)
2. API 直接抓取 PCF 數據 (備用方式)
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from playwright.sync_api import sync_playwright
import time
import random
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from loguru import logger
import pandas as pd

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
    INFO_URL = "https://www.ezmoney.com.tw/ETF/Fund/Info"
    
    def __init__(self):
        """初始化爬蟲"""
        self.session = self._create_session()
        self.request_count = 0
        # 建立下載目錄
        self.download_dir = Path('downloads/ezmoney')
        self.download_dir.mkdir(parents=True, exist_ok=True)
    
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
    
    def download_portfolio_excel(
        self,
        fund_code: str,
        date: str
    ) -> Optional[Path]:
        """
        使用 Playwright 下載基金投資組合 Excel
        
        Args:
            fund_code: EZMoney 基金代碼 (例如: 49YTW)
            date: 日期 (YYYY-MM-DD)，僅用於檔名
        
        Returns:
            Optional[Path]: 下載的檔案路徑，失敗則返回 None
        """
        logger.info(f"Downloading portfolio Excel for fund {fund_code}")
        
        downloaded_file = None
        
        try:
            with sync_playwright() as p:
                # 使用無頭模式（CI 環境需要）
                browser = p.chromium.launch(headless=True)
                
                # 設定下載路徑
                context = browser.new_context(
                    accept_downloads=True,
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
                
                page = context.new_page()
                
                # 訪問基金資訊頁面
                url = f"{self.INFO_URL}?fundCode={fund_code}"
                logger.debug(f"Navigating to {url}")
                page.goto(url, timeout=30000)
                
                # 等待頁面加載
                time.sleep(2)
                
                # 點擊「基金投資組合」標籤
                logger.debug("Clicking '基金投資組合' tab")
                try:
                    # 嘗試多種選擇器
                    selectors = [
                        'text="基金投資組合"',
                        'a:has-text("基金投資組合")',
                        '#tab-portfolio',
                        '.nav-tabs a:has-text("基金投資組合")'
                    ]
                    
                    for selector in selectors:
                        try:
                            page.click(selector, timeout=5000)
                            logger.debug(f"Clicked tab using selector: {selector}")
                            break
                        except:
                            continue
                    
                    time.sleep(2)
                except Exception as e:
                    logger.warning(f"Could not click portfolio tab: {e}")
                    # 繼續執行，可能預設就在投資組合頁
                
                # 查找並點擊「匯出XLSX」按鈕
                logger.debug("Looking for Excel export button")
                
                # 開始下載監聽
                with page.expect_download(timeout=30000) as download_info:
                    # 嘗試多種按鈕選擇器
                    button_selectors = [
                        'text="匯出XLSX"',
                        'button:has-text("匯出")',
                        'a:has-text("匯出XLSX")',
                        '.btn:has-text("匯出")',
                        'input[value*="匯出"]'
                    ]
                    
                    clicked = False
                    for selector in button_selectors:
                        try:
                            page.click(selector, timeout=5000)
                            logger.debug(f"Clicked export button using selector: {selector}")
                            clicked = True
                            break
                        except:
                            continue
                    
                    if not clicked:
                        logger.error("Could not find export button")
                        browser.close()
                        return None
                
                download = download_info.value
                
                # 儲存檔案
                filename = f"{fund_code}_{date.replace('-', '')}.xlsx"
                save_path = self.download_dir / filename
                download.save_as(save_path)
                
                logger.info(f"Downloaded file: {save_path}")
                downloaded_file = save_path
                
                browser.close()
        
        except Exception as e:
            logger.error(f"Error downloading Excel: {e}")
            logger.exception(e)
        
        return downloaded_file
    
    def parse_excel_file(
        self,
        excel_path: Path,
        etf_code: str,
        date: str
    ) -> List[Dict[str, Any]]:
        """
        解析下載的 Excel 檔案
        
        Args:
            excel_path: Excel 檔案路徑
            etf_code: ETF 代碼
            date: 日期 (YYYY-MM-DD)
        
        Returns:
            List[Dict]: 持股明細列表
        """
        logger.info(f"Parsing Excel file: {excel_path}")
        
        holdings = []
        
        try:
            # EZMoney 的 Excel 格式特殊：
            # - 前面有基金資訊（淨資產、單位淨值等）
            # - 第 18 行（索引 18）是表頭：股票代號、股票名稱、股數、持股權重
            # - 第 19 行開始是股票數據
            
            # 直接跳過前 19 行，手動指定列名
            df = pd.read_excel(
                excel_path, 
                skiprows=19,
                names=['股票代號', '股票名稱', '股數', '持股權重']
            )
            
            logger.debug(f"Loaded {len(df)} rows from Excel")
            
            logger.debug(f"Excel columns: {df.columns.tolist()}")
            logger.debug(f"Excel shape: {df.shape}")
            
            # 欄位名稱對照
            col_mapping = {
                'code': None,
                'name': None,
                'shares': None,
                'weight': None
            }
            
            for col in df.columns:
                col_str = str(col)
                if '股票代號' in col_str or '股票代碼' in col_str or '代碼' in col_str:
                    col_mapping['code'] = col
                elif '股票名稱' in col_str or '名稱' in col_str:
                    col_mapping['name'] = col
                elif '股數' in col_str:
                    col_mapping['shares'] = col
                elif '權重' in col_str or '比例' in col_str or '持股權重' in col_str:
                    col_mapping['weight'] = col
            
            logger.debug(f"Column mapping: {col_mapping}")
            
            if not col_mapping['code'] or not col_mapping['name']:
                logger.error("Cannot find required columns in Excel file")
                return []
            
            # 解析每一行
            for idx, row in df.iterrows():
                try:
                    stock_code = str(row[col_mapping['code']]).strip()
                    stock_name = str(row[col_mapping['name']]).strip()
                    
                    # 跳過空白行或非股票行
                    if not stock_code or stock_code == 'nan':
                        continue
                    
                    # 只處理4位數字的台股代碼
                    if not stock_code.isdigit() or len(stock_code) != 4:
                        continue
                    
                    holding = {
                        'etf_code': etf_code,
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'shares': self._parse_number(row[col_mapping['shares']]) if col_mapping['shares'] else 0,
                        'market_value': 0,  # Excel 檔案中沒有市值欄位
                        'weight': self._parse_percentage(row[col_mapping['weight']]) if col_mapping['weight'] else 0.0,
                        'date': date
                    }
                    
                    holdings.append(holding)
                    
                except Exception as e:
                    logger.debug(f"Skipping row {idx}: {e}")
                    continue
            
            logger.info(f"Parsed {len(holdings)} holdings from Excel")
        
        except Exception as e:
            logger.error(f"Error parsing Excel file: {e}")
            logger.exception(e)
        
        return holdings
    
    def get_etf_holdings(
        self, 
        etf_code: str, 
        date: str,
        use_excel: bool = True
    ) -> List[Dict[str, Any]]:
        """
        獲取指定 ETF 在特定日期的持股明細
        
        Args:
            etf_code: ETF 代碼 (例如: 00981A)
            date: 日期 (YYYY-MM-DD)
            use_excel: 是否使用 Excel 下載方式（預設 True），False 則使用 API
        
        Returns:
            List[Dict]: 持股明細列表
        """
        # 獲取基金代碼
        fund_code = self.get_fund_code(etf_code)
        if not fund_code:
            logger.error(f"Cannot fetch holdings: ETF {etf_code} not in mapping")
            return []
        
        # 方法1: 使用 Excel 下載 (主要方式)
        if use_excel:
            logger.info(f"Using Excel download method for {etf_code}")
            excel_path = self.download_portfolio_excel(fund_code, date)
            
            if excel_path and excel_path.exists():
                holdings = self.parse_excel_file(excel_path, etf_code, date)
                if holdings:
                    return holdings
                else:
                    logger.warning("Excel parsing returned no holdings, falling back to API")
            else:
                logger.warning("Excel download failed, falling back to API")
        
        # 方法2: 使用 API (備用方式)
        logger.info(f"Using API method for {etf_code}")
        return self._get_holdings_from_api(etf_code, fund_code, date)
    
    def _get_holdings_from_api(
        self,
        etf_code: str,
        fund_code: str,
        date: str
    ) -> List[Dict[str, Any]]:
        """
        從 API 獲取持股數據（原有方法）
        
        Args:
            etf_code: ETF 代碼
            fund_code: 基金代碼
            date: 日期
        
        Returns:
            List[Dict]: 持股明細列表
        """
        # 抓取 PCF 數據
        data = self.get_pcf_data(fund_code, date)
        if not data:
            logger.error(f"Failed to fetch PCF data for {etf_code}")
            return []
        
        holdings = []
        
        try:
            # 解析 API 數據結構
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
