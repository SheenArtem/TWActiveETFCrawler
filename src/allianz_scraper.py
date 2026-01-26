"""
安聯投信 ETF 爬蟲模組
使用 Playwright 訪問持股頁面並從 DOM 提取數據
"""
from playwright.sync_api import sync_playwright
import time
import random
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from loguru import logger

from .config import (
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX
)


# 安聯投信 ETF 基金代碼對照表
ALLIANZ_ETF_CODES = {
    '00984A': 'E0001',  # 安聯台灣高息成長主動式ETF
    # 未來可以新增其他安聯投信 ETF
}


class AllianzScraper:
    """安聯投信網站 ETF 爬蟲（使用 Playwright DOM 提取）"""
    
    BASE_URL = "https://etf.allianzgi.com.tw"
    DETAIL_URL = "/etf-info/{fund_id}?tab=4"  # tab=4 是持股比重標籤
    
    def __init__(self):
        """初始化爬蟲"""
        self.request_count = 0
    
    def _random_delay(self):
        """隨機延遲，避免被封鎖"""
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        logger.debug(f"Waiting {delay:.2f} seconds...")
        time.sleep(delay)
    
    def get_fund_id(self, etf_code: str) -> Optional[str]:
        """
        獲取 ETF 在安聯投信網站的基金代碼
        
        Args:
            etf_code: ETF 代碼 (例如: 00984A)
        
        Returns:
            Optional[str]: 基金代碼，若未找到則返回 None
        """
        fund_id = ALLIANZ_ETF_CODES.get(etf_code)
        if not fund_id:
            logger.warning(f"ETF {etf_code} not found in Allianz code mapping")
        return fund_id
    
    def get_holdings_with_playwright(
        self, 
        fund_id: str,
        date: str
    ) -> List[Dict[str, Any]]:
        """
        使用 Playwright 訪問持股頁面並提取數據
        
        Args:
            fund_id: 安聯投信基金代碼 (例如: E0001)
            date: 日期 (YYYY-MM-DD)
        
        Returns:
            List[Dict]: 持股明細列表
        """
        holdings = []
        
        try:
            url = f"{self.BASE_URL}{self.DETAIL_URL.format(fund_id=fund_id)}"
            logger.info(f"Fetching holdings from {url}")
            
            with sync_playwright() as p:
                # 使用無頭模式
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                
                # 訪問持股頁面
                logger.debug(f"Navigating to {url}")
                page.goto(url, timeout=60000)
                
                # 等待頁面加載
                logger.debug("Waiting for page to load...")
                time.sleep(3)
                
                # 循環點擊「顯示更多」按鈕直到所有持股顯示
                logger.debug("Clicking '顯示更多' button to load all holdings...")
                click_count = 0
                max_clicks = 20  # 防止無限循環
                
                while click_count < max_clicks:
                    # 尋找「顯示更多」按鈕
                    show_more_buttons = page.locator('text="顯示更多"').all()
                    
                    if len(show_more_buttons) == 0:
                        logger.debug("No more '顯示更多' buttons found")
                        break
                    
                    # 點擊第一個「顯示更多」按鈕
                    try:
                        show_more_buttons[0].click(timeout=5000)
                        click_count += 1
                        logger.debug(f"Clicked '顯示更多' button {click_count} times")
                        time.sleep(1)  # 等待數據加載
                    except Exception as e:
                        logger.debug(f"Error clicking button: {e}")
                        break
                
                logger.info(f"Clicked '顯示更多' {click_count} times")
                
                # 提取表格數據
                logger.debug("Extracting table data...")
                holdings = self._extract_holdings_from_page(page, date)
                
                browser.close()
        
        except Exception as e:
            logger.error(f"Error fetching holdings with Playwright: {e}")
            logger.exception(e)
        
        return holdings
    
    def _extract_holdings_from_page(
        self, 
        page,
        date: str
    ) -> List[Dict[str, Any]]:
        """
        從頁面 DOM 提取持股數據
        
        Args:
            page: Playwright Page 對象
            date: 日期 (YYYY-MM-DD)
        
        Returns:
            List[Dict]: 持股明細列表
        """
        holdings = []
        
        try:
            # 尋找所有表格
            tables = page.locator('table').all()
            logger.debug(f"Found {len(tables)} tables on page")
            
            for table_idx, table in enumerate(tables):
                # 獲取表格的所有行
                rows = table.locator('tr').all()
                logger.debug(f"Table {table_idx}: {len(rows)} rows")
                
                # 檢查是否是持股表格（應該包含：序號、股票代號、股票名稱、股數、權重）
                if len(rows) < 2:
                    continue
                
                # 檢查標題行
                header_row = rows[0]
                header_text = header_row.inner_text()
                
                if '股票代號' not in header_text or '股票名稱' not in header_text:
                    logger.debug(f"Table {table_idx} is not a stock holdings table")
                    continue
                
                logger.info(f"Found holdings table at index {table_idx}")
                
                # 解析數據行（跳過標題行）
                for row_idx, row in enumerate(rows[1:], 1):
                    try:
                        cells = row.locator('td').all()
                        
                        if len(cells) < 5:
                            logger.debug(f"Row {row_idx} has insufficient cells: {len(cells)}")
                            continue
                        
                        # 提取數據：序號、股票代號、股票名稱、股數、權重(%)
                        # 索引可能需要調整，根據實際表格結構
                        stock_code = cells[1].inner_text().strip()
                        stock_name = cells[2].inner_text().strip()
                        shares_text = cells[3].inner_text().strip()
                        weight_text = cells[4].inner_text().strip()
                        
                        # 驗證股票代號（應該是4位數字）
                        if not (stock_code.isdigit() and len(stock_code) == 4):
                            logger.debug(f"Skipping invalid stock code: {stock_code}")
                            continue
                        
                        holding = {
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'shares': self._parse_number(shares_text),
                            'weight': self._parse_percentage(weight_text),
                            'date': date
                        }
                        
                        holdings.append(holding)
                    
                    except Exception as e:
                        logger.debug(f"Error parsing row {row_idx}: {e}")
                        continue
            
            logger.info(f"Extracted {len(holdings)} holdings from page")
        
        except Exception as e:
            logger.error(f"Error extracting holdings from page: {e}")
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
            etf_code: ETF 代碼 (例如: 00984A)
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
        
        # 使用 Playwright 獲取持股
        holdings = self.get_holdings_with_playwright(fund_id, date)
        
        # 添加 ETF 代碼到每筆持股
        for holding in holdings:
            holding['etf_code'] = etf_code
            holding['market_value'] = 0  # 安聯網站沒有提供市值
        
        return holdings
    
    @staticmethod
    def _parse_number(value: str) -> int:
        """
        解析數字（移除逗號等格式）
        
        Args:
            value: 原始數值字串
        
        Returns:
            int: 解析後的整數
        """
        if not value:
            return 0
        clean_value = value.replace(',', '').replace(' ', '').strip()
        try:
            return int(float(clean_value))
        except:
            return 0
    
    @staticmethod
    def _parse_percentage(value: str) -> float:
        """
        解析百分比（移除 % 符號）
        
        Args:
            value: 原始數值字串
        
        Returns:
            float: 解析後的浮點數
        """
        if not value:
            return 0.0
        clean_value = value.replace('%', '').replace(',', '').replace(' ', '').strip()
        try:
            return float(clean_value)
        except:
            return 0.0
    
    def add_etf_mapping(self, etf_code: str, fund_id: str):
        """
        新增 ETF 與安聯投信基金代碼的對照
        
        Args:
            etf_code: ETF 代碼 (例如: 00984A)
            fund_id: 安聯投信基金代碼 (例如: E0001)
        """
        ALLIANZ_ETF_CODES[etf_code] = fund_id
        logger.info(f"Added ETF mapping: {etf_code} -> {fund_id}")
    
    def get_all_mappings(self) -> Dict[str, str]:
        """
        獲取所有 ETF 對照表
        
        Returns:
            Dict[str, str]: ETF 代碼對照字典
        """
        return ALLIANZ_ETF_CODES.copy()
