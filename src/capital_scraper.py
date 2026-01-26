"""
群益證券投信 ETF 爬蟲模組
使用 Playwright 下載 Excel 文件並解析
"""
from playwright.sync_api import sync_playwright
import time
import random
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
import pandas as pd
from loguru import logger

from .config import (
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX
)


# 群益證券投信 ETF 基金代碼對照表
CAPITAL_ETF_CODES = {
    '00982A': '399',  # 群益台灣精選強棒
    '00992A': '500',  # 群益科技創新
    # 未來可以新增其他群益證券 ETF
}


class CapitalScraper:
    """群益證券投信網站 ETF 爬蟲（使用 Excel 下載）"""
    
    BASE_URL = "https://www.capitalfund.com.tw/etf/product/detail/{fund_id}/portfolio"
    
    def __init__(self):
        """初始化爬蟲"""
        self.request_count = 0
        self.download_dir = Path("downloads/capital")
        self.download_dir.mkdir(parents=True, exist_ok=True)
    
    def _random_delay(self):
        """隨機延遲，避免被封鎖"""
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        logger.debug(f"Waiting {delay:.2f} seconds...")
        time.sleep(delay)
    
    def get_fund_id(self, etf_code: str) -> Optional[str]:
        """
        獲取 ETF 在群益證券網站的基金代碼
        
        Args:
            etf_code: ETF 代碼 (例如: 00982A)
        
        Returns:
            Optional[str]: 基金代碼，若未找到則返回 None
        """
        fund_id = CAPITAL_ETF_CODES.get(etf_code)
        if not fund_id:
            logger.warning(f"ETF {etf_code} not found in Capital code mapping")
        return fund_id
    
    def download_portfolio_excel(
        self, 
        fund_id: str,
        date: str
    ) -> Optional[Path]:
        """
        使用 Playwright 下載投資組合 Excel 文件
        
        Args:
            fund_id: 群益證券基金代碼 (例如: 399)
            date: 日期 (YYYY-MM-DD)
        
        Returns:
            Optional[Path]: 下載的文件路徑，失敗時返回 None
        """
        url = self.BASE_URL.format(fund_id=fund_id)
        logger.info(f"Downloading portfolio Excel for fund {fund_id} on {date}")
        logger.debug(f"URL: {url}")
        
        downloaded_file = None
        
        try:
            with sync_playwright() as p:
                # 啟動瀏覽器
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(accept_downloads=True)
                page = context.new_page()
                
                # 訪問頁面
                logger.debug("Navigating to page...")
                page.goto(url, timeout=60000)
                
                # 等待頁面加載
                logger.debug("Waiting for page to load...")
                time.sleep(5)
                
                # 選擇日期（如果有日期選擇器的話)
                # 這部分可能需要根據實際情況調整
                try:
                    # 尋找日期輸入框
                    date_input = page.locator('input[type="date"], input[placeholder*="日期"]').first
                    if date_input.count() > 0:
                        # 轉換日期格式為網站需要的格式
                        date_str = datetime.strptime(date, '%Y-%m-%d').strftime('%Y/%m/%d')
                        date_input.fill(date_str)
                        logger.info(f"Set date to: {date_str}")
                        time.sleep(1)
                except Exception as e:
                    logger.debug(f"Could not set date (may not be needed): {e}")
                
                # 點擊下載按鈕
                logger.debug("Looking for download button...")
                
                # 嘗試找到並點擊下載按鈕
                download_button = page.locator('text="下載資料"').first
                if download_button.count() > 0:
                    logger.info("Found download button, clicking...")
                    
                    # 正確的下載方式：使用 expect_download
                    with page.expect_download(timeout=30000) as download_info:
                        download_button.click()
                    
                    download = download_info.value
                    
                    # 儲存文件
                    filename = f"{fund_id}_{date.replace('-', '')}.xlsx"
                    save_path = self.download_dir / filename
                    download.save_as(save_path)
                    
                    logger.info(f"Downloaded file: {save_path}")
                    downloaded_file = save_path
                else:
                    logger.error("Download button not found")
                
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
        解析 Excel 文件提取持股明細
        
        Args:
            excel_path: Excel 文件路徑
            etf_code: ETF 代碼
            date: 日期 (YYYY-MM-DD)
        
        Returns:
            List[Dict]: 持股明細列表
        """
        holdings = []
        
        try:
            logger.info(f"Parsing Excel file: {excel_path}")
            
            # Excel 文件有多個 sheets，持股明細在「股票」sheet
            sheet_name = '股票'
            
            # 讀取 Excel 文件的指定 sheet
            df = pd.read_excel(excel_path, sheet_name=sheet_name)
            
            logger.debug(f"Excel sheet '{sheet_name}' columns: {df.columns.tolist()}")
            logger.debug(f"Excel shape: {df.shape}")
            
            # 群益證券的欄位名稱：股票代號、股票名稱、持股權重(%)、股數
            code_col = '股票代號'
            name_col = '股票名稱'
            weight_col = '持股權重(%)'
            shares_col = '股數'
            
            # 驗證欄位是否存在
            required_cols = [code_col, name_col, weight_col, shares_col]
            missing_cols = [col for col in required_cols if col not in df.columns]
            
            if missing_cols:
                logger.error(f"Missing required columns: {missing_cols}")
                logger.error(f"Available columns: {df.columns.tolist()}")
                return []
            
            logger.debug(f"Found all required columns")
            
            # 解析每一行
            for idx, row in df.iterrows():
                try:
                    stock_code = str(row[code_col]).strip()
                    stock_name = str(row[name_col]).strip()
                    
                    # 驗證股票代號（應該是4位數字）
                    if not (stock_code.isdigit() and len(stock_code) == 4):
                        logger.debug(f"Skipping invalid stock code: {stock_code}")
                        continue
                    
                    holding = {
                        'etf_code': etf_code,
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'weight': self._parse_percentage(row[weight_col]),
                        'shares': self._parse_number(row[shares_col]),
                        'market_value': 0,
                        'date': date
                    }
                    
                    holdings.append(holding)
                
                except Exception as e:
                    logger.debug(f"Error parsing row {idx}: {e}")
                    continue
            
            logger.info(f"Parsed {len(holdings)} holdings from Excel")
        
        except Exception as e:
            logger.error(f"Error parsing Excel file: {e}")
            logger.exception(e)
        
        return holdings
    
    def get_etf_holdings(
        self, 
        etf_code: str, 
        date: str
    ) -> List[Dict[str, Any]]:
        """
        獲取指定 ETF 在特定日期的持股明細
        
        Args:
            etf_code: ETF 代碼 (例如: 00982A)
            date: 日期 (YYYY-MM-DD)
        
        Returns:
            List[Dict]: 持股明細列表
        """
        self._random_delay()
        self.request_count += 1
        
        # 獲取基金代碼
        fund_id = self.get_fund_id(etf_code)
        if not fund_id:
            logger.error(f"Cannot fetch holdings: ETF {etf_code} not in mapping")
            return []
        
        # 下載 Excel 文件
        excel_path = self.download_portfolio_excel(fund_id, date)
        if not excel_path or not excel_path.exists():
            logger.error(f"Failed to download Excel file for {etf_code}")
            return []
        
        # 解析 Excel 文件
        holdings = self.parse_excel_file(excel_path, etf_code, date)
        
        # 清理下載的文件（可選）
        # excel_path.unlink()
        
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
        if pd.isna(value):
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            clean_value = value.replace(',', '').replace(' ', '').replace('%', '').strip()
            try:
                return int(float(clean_value))
            except:
                return 0
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
        if pd.isna(value):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            clean_value = value.replace('%', '').replace(',', '').replace(' ', '').strip()
            try:
                return float(clean_value)
            except:
                return 0.0
        return 0.0
    
    def add_etf_mapping(self, etf_code: str, fund_id: str):
        """
        新增 ETF 與群益證券基金代碼的對照
        
        Args:
            etf_code: ETF 代碼 (例如: 00982A)
            fund_id: 群益證券基金代碼 (例如: 399)
        """
        CAPITAL_ETF_CODES[etf_code] = fund_id
        logger.info(f"Added ETF mapping: {etf_code} -> {fund_id}")
    
    def get_all_mappings(self) -> Dict[str, str]:
        """
        獲取所有 ETF 對照表
        
        Returns:
            Dict[str, str]: ETF 代碼對照字典
        """
        return CAPITAL_ETF_CODES.copy()
