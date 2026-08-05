"""
群益證券投信 ETF 爬蟲模組

主路徑：buyback API（申購買回清單，即 PCF）。
資料來源原則是「下載檔案 > DOM > API」，群益是**已記錄的例外**（2026-08-05 實測）：
官網下載的 Excel 四個 sheet 與檔名都沒有資料日期，頁面上唯一的日期是「最新預估淨值」
的報價日；只有 `POST /CFWeb/api/etf/buyback` 回帶 `data.pcf.date2`（持股基準日）。
沿用 Excel 就得用請求日期，群益因此曾是歷史錯位第二大戶（15 組）。
API 與 Excel 是同一份資料（nav、股數逐筆一致），差別只在 API 多帶日期。

已知風險（walk 進 API 的代價）：欄位改名或改版不會有下載按鈕壞掉那種明顯訊號。
緩解：_parse_api_response 對缺欄位保守退回，且保留原 Playwright+Excel 路徑當備援
（備援不帶 source_dated，寫入層防護會對它生效）。

日期欄位語意（2026-08-05 實測）：
- `data.pcf.date2` = 持股基準日（要用這個）
- `data.pcf.date1`、每筆股票的 `date1` = 下一交易日（PCF 適用日），**勿用**——
  與摩根 PCF 的估值日同款前瞻模式。
"""
from playwright.sync_api import sync_playwright
import requests
import time
import random
import re
import urllib3
from typing import List, Dict, Any, Optional, Tuple
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
    """群益證券投信網站 ETF 爬蟲（buyback API 為主，Excel 下載為備援）"""

    BASE_URL = "https://www.capitalfund.com.tw/etf/product/detail/{fund_id}/portfolio"
    BUYBACK_API = "https://www.capitalfund.com.tw/CFWeb/api/etf/buyback"

    def __init__(self):
        """初始化爬蟲"""
        self.request_count = 0
        self.download_dir = Path("downloads/capital")
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def _fetch_buyback(self, fund_id: str) -> Optional[Dict[str, Any]]:
        """呼叫 buyback API（申購買回清單）。失敗回傳 None，由呼叫端退回 Excel 備援。"""
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        try:
            resp = requests.post(
                self.BUYBACK_API,
                json={"fundId": fund_id},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Referer": self.BASE_URL.format(fund_id=fund_id),
                    "Accept": "application/json",
                },
                timeout=30,
                verify=False,
            )
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.warning(f"Capital buyback API failed for fund {fund_id}: {e}")
            return None

    @staticmethod
    def _parse_api_response(
        payload: Dict[str, Any], etf_code: str, fallback_date: str
    ) -> Tuple[List[Dict[str, Any]], str, bool]:
        """
        解析 buyback API 回應。

        `data.pcf.date2` 是持股基準日；`date1`（pcf 層與每筆股票都有）是下一交易日的
        PCF 適用日，**勿用**。date2 缺漏或格式不對時退回請求日期且不標 source_dated，
        寫入層的日期錯位防護會繼續生效。

        Returns:
            (持股列表, 資料日期, 是否真的取自來源)
        """
        data = (payload or {}).get('data') or {}
        stocks = data.get('stocks') or []

        date2 = str(((data.get('pcf') or {}).get('date2')) or '').strip()
        if re.fullmatch(r'20\d{2}-\d{2}-\d{2}', date2):
            actual_date, source_dated = date2, True
            if actual_date != fallback_date:
                logger.info(
                    f"Capital data date from buyback API: {actual_date} (requested {fallback_date})"
                )
        else:
            actual_date, source_dated = fallback_date, False
            logger.warning(
                f"Capital: pcf.date2 missing or malformed ({date2!r}); "
                f"falling back to requested date {fallback_date}"
            )

        holdings = []
        for s in stocks:
            stock_code = str(s.get('stocNo') or '').strip()
            if not (stock_code.isdigit() and len(stock_code) == 4):
                continue
            try:
                shares = int(float(s.get('share') or 0))
            except (TypeError, ValueError):
                shares = 0
            try:
                weight = float(s.get('weight') or 0)
            except (TypeError, ValueError):
                weight = 0.0
            holdings.append({
                'etf_code': etf_code,
                'stock_code': stock_code,
                'stock_name': str(s.get('stocName') or '').strip(),
                'shares': shares,
                'weight': weight,
                'market_value': 0,
                'date': actual_date,
                'source_dated': source_dated,
            })

        return holdings, actual_date, source_dated
    
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

                # 等待 SPA 渲染出下載按鈕（取代固定 sleep，避免 CI 環境載入較慢時錯過）
                logger.debug("Waiting for download button to render...")
                try:
                    page.wait_for_selector('text="下載資料"', state='visible', timeout=45000)
                except Exception as e:
                    logger.warning(f"Download button not visible within 45s, retrying after reload: {e}")
                    page.reload(timeout=60000)
                    page.wait_for_selector('text="下載資料"', state='visible', timeout=45000)
                
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
                
                # 點擊下載按鈕（到此 wait_for_selector 已確保按鈕可見）
                logger.debug("Clicking download button...")
                download_button = page.locator('text="下載資料"').first

                with page.expect_download(timeout=30000) as download_info:
                    download_button.click()

                download = download_info.value

                # 儲存文件
                filename = f"{fund_id}_{date.replace('-', '')}.xlsx"
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

        # 主路徑：buyback API（帶持股基準日 date2，見模組 docstring 的例外理由）
        payload = self._fetch_buyback(fund_id)
        if payload:
            holdings, actual_date, source_dated = self._parse_api_response(
                payload, etf_code, date
            )
            if holdings:
                logger.info(
                    f"Capital: parsed {len(holdings)} holdings for {etf_code} via buyback API "
                    f"(data date: {actual_date}, source_dated={source_dated})"
                )
                return holdings
            logger.warning(
                f"Capital: buyback API returned no parsable stocks for {etf_code}; "
                f"falling back to Excel download"
            )

        # 備援：原 Playwright 下載 Excel。Excel 無資料日期，只能用請求日期，
        # 不帶 source_dated —— 寫入層的日期錯位防護會對這條路徑生效。
        excel_path = self.download_portfolio_excel(fund_id, date)
        if not excel_path or not excel_path.exists():
            logger.error(f"Failed to download Excel file for {etf_code}")
            return []

        return self.parse_excel_file(excel_path, etf_code, date)
    
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
