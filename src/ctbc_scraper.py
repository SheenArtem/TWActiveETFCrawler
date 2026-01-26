"""
中信投信 ETF 爬蟲模組
使用 Playwright 訪問持股頁面並從 DOM (div 結構) 提取數據
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


# 中信投信 ETF 基金代碼對照表
CTBC_ETF_CODES = {
    '00995A': '00653201',  # 中國信託台灣卓越成長主動式ETF基金
    # 未來可以新增其他中信投信 ETF
}


class CTBCScraper:
    """中信投信網站 ETF 爬蟲（使用 Playwright DOM 提取）"""
    
    BASE_URL = "https://www.ctbcinvestments.com"
    DETAIL_URL = "/Etf/{fund_id}/Combination"
    
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
        獲取 ETF 在中信投信網站的基金代碼
        
        Args:
            etf_code: ETF 代碼 (例如: 00995A)
        
        Returns:
            Optional[str]: 基金代碼，若未找到則返回 None
        """
        fund_id = CTBC_ETF_CODES.get(etf_code)
        if not fund_id:
            logger.warning(f"ETF {etf_code} not found in CTBC code mapping")
        return fund_id
    
    def get_holdings_with_playwright(
        self, 
        fund_id: str,
        date: str
    ) -> List[Dict[str, Any]]:
        """
        使用 Playwright 下載並解析 Excel
        
        Args:
            fund_id: 中信投信基金代碼 (例如: 00653201)
            date: 日期 (YYYY-MM-DD)
        
        Returns:
            List[Dict]: 持股明細列表
        """
        import pandas as pd
        import random
        
        holdings = []
        temp_file = None
        
        try:
            url = f"{self.BASE_URL}{self.DETAIL_URL.format(fund_id=fund_id)}"
            logger.info(f"Fetching holdings from {url} via Excel download")
            
            with sync_playwright() as p:
                # 使用有頭模式並添加反爬蟲參數
                browser = p.chromium.launch(
                    headless=False,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                    ]
                )
                
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080},
                    accept_downloads=True
                )
                
                page = context.new_page()
                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                """)
                
                try:
                    logger.debug(f"Navigating to {url}")
                    page.goto(url, timeout=60000, wait_until='domcontentloaded')
                    
                    # 等待頁面載入
                    time.sleep(5 + random.random() * 3)
                    
                    # 尋找包含 "下載EXCEL" 的元素，或者下載圖標
                    # 根據 HTML 分析，下載按鈕可能是一個帶有特定圖片的 button
                    # 之前在 HTML 看到了 "下載EXCEL" 的文字在 span 中，但可能是隱藏的
                    # 我們嘗試尋找 button 裡面包含 text="下載EXCEL" 或者 img src 包含 download 或 excel
                    
                    # 嘗試各種可能的選擇器
                    download_btn = None
                    
                    # 1. 根據文字
                    btn_by_text = page.locator('button', has_text='下載EXCEL')
                    if btn_by_text.count() > 0 and btn_by_text.first.is_visible():
                        download_btn = btn_by_text.first
                    
                    # 2. 根據 span 文字 (如果 button 包 span)
                    if not download_btn:
                         span_btn = page.locator('span', has_text='下載EXCEL')
                         if span_btn.count() > 0:
                             # 找它的父 button
                             parent = span_btn.first.locator('..')
                             if parent.count() > 0: download_btn = parent
                    
                    # 3. 根據圖片 (如果文字是圖片)
                    # 無法確切知道圖片，嘗試通用按鈕
                    if not download_btn:
                        # 找頁面上的 button，排除 header/footer
                        pass

                    if download_btn:
                        logger.info("Found download button, clicking...")
                        with page.expect_download(timeout=30000) as download_info:
                            try:
                                download_btn.click()
                            except:
                                # 有時候點擊會因為遮擋失敗，嘗試 force click
                                download_btn.click(force=True)
                                
                        download = download_info.value
                        temp_file = download.path()
                        logger.info(f"Downloaded file to {temp_file}")
                        
                        # 解析 Excel
                        holdings = self._parse_excel(temp_file, date)
                        
                    else:
                        logger.error("Download button not found")
                        # 備案：嘗試截圖幫助調試
                        page.screenshot(path="debug_no_download_btn.png")
                        
                except Exception as e:
                    logger.error(f"Error during Playwright interaction: {e}")
                    page.screenshot(path="debug_error.png")
                
                finally:
                    browser.close()
                    
        except Exception as e:
            logger.error(f"Error fetching holdings from CTBC: {e}")
            logger.exception(e)
            
        return holdings

    def _parse_excel(self, file_path, date):
        """解析下載的 Excel 檔案"""
        import pandas as pd
        holdings = []
        try:
            # 讀取 Excel，可能有多個 sheet 或 header 位置不固定
            # 先讀取前幾行來判斷
            df = pd.read_excel(file_path)
            
            # 中信的 Excel 格式通常類似網頁表格
            # 尋找包含 "股票代碼" 的行作為 header
            header_row = None
            for i, row in df.iterrows():
                row_values = [str(x) for x in row.values if pd.notna(x)]
                if any("股票代碼" in x for x in row_values):
                    header_row = i
                    break
            
            if header_row is not None:
                # 重新讀取，指定 header
                df = pd.read_excel(file_path, header=header_row+1)
                
                # 遍歷數據
                for _, row in df.iterrows():
                    try:
                        # 預期欄位: 序號, 股票代碼, 中文名稱, 英文名稱, 股數, 權重(%)
                        # 需根據欄位名稱自動對應
                        
                        # 尋找欄位名
                        code_col = next((c for c in df.columns if "股票代碼" in str(c)), None)
                        name_col = next((c for c in df.columns if "中文名稱" in str(c)), None)
                        shares_col = next((c for c in df.columns if "股數" in str(c)), None)
                        weight_col = next((c for c in df.columns if "權重" in str(c)), None)
                        
                        if code_col and name_col:
                            code = str(row[code_col]).strip().split('.')[0] # 處理可能的浮點數代碼
                            name = str(row[name_col]).strip()
                            
                            if code.isdigit() and len(code) == 4:
                                shares = 0
                                weight = 0.0
                                
                                if shares_col and pd.notna(row[shares_col]):
                                    shares = self._parse_number(str(row[shares_col]))
                                
                                if weight_col and pd.notna(row[weight_col]):
                                    weight = self._parse_percentage(str(row[weight_col]))
                                
                                holdings.append({
                                    'stock_code': code,
                                    'stock_name': name,
                                    'shares': shares,
                                    'weight': weight,
                                    'date': date
                                })
                    except Exception as e:
                        logger.warning(f"Error parsing row: {e}")
                        continue
            
            logger.info(f"Parsed {len(holdings)} holdings from Excel")
            
        except Exception as e:
            logger.error(f"Error parsing Excel: {e}")
        
        return holdings

    def _extract_from_table(self, rows, date):
        """備用：從標準表格提取"""
        holdings = []
        for row in rows[1:]: # Skip header
            cells = row.locator('td').all()
            if len(cells) >= 5:
                # 假設: Index, Code, Name(Ch), Name(En), Shares, Weight
                try:
                    code = cells[1].inner_text().strip()
                    name = cells[2].inner_text().strip()
                    shares = self._parse_number(cells[4].inner_text())
                    weight = self._parse_percentage(cells[5].inner_text())
                    
                    if code.isdigit() and len(code) == 4:
                        holdings.append({
                            'stock_code': code,
                            'stock_name': name,
                            'shares': shares,
                            'weight': weight,
                            'date': date
                        })
                except Exception:
                    pass
        return holdings
    
    def get_etf_holdings(
        self, 
        etf_code: str, 
        date: str
    ) -> List[Dict[str, Any]]:
        """
        獲取指定 ETF 在特定日期的持股明細
        
        Args:
            etf_code: ETF 代碼 (例如: 00995A)
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
            holding['market_value'] = 0  # 網站通常不提供市值或需計算
        
        return holdings
    
    @staticmethod
    def _parse_number(value: str) -> int:
        """解析數字"""
        if not value: return 0
        clean = value.replace(',', '').replace(' ', '').strip()
        try: return int(float(clean))
        except: return 0
    
    @staticmethod
    def _parse_percentage(value: str) -> float:
        """解析百分比"""
        if not value: return 0.0
        clean = value.replace('%', '').replace(',', '').replace(' ', '').strip()
        try: return float(clean)
        except: return 0.0
    
    def add_etf_mapping(self, etf_code: str, fund_id: str):
        CTBC_ETF_CODES[etf_code] = fund_id
        logger.info(f"Added ETF mapping: {etf_code} -> {fund_id}")
    
    def get_all_mappings(self) -> Dict[str, str]:
        return CTBC_ETF_CODES.copy()
