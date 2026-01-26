"""
復華投信 ETF 爬蟲模組
使用 API 下載 Excel 文件並解析
"""
import requests
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


# 復華投信 ETF 基金代碼對照表
FHTRUST_ETF_CODES = {
    '00991A': 'ETF23',  # 復華台灣未來50主動式ETF基金
    # 未來可以新增其他復華投信 ETF
}


class FHTrustScraper:
    """復華投信網站 ETF 爬蟲（使用 API 下載 Excel）"""
    
    BASE_URL = "https://www.fhtrust.com.tw"
    EXCEL_API = "/api/assetsExcel/{fund_id}/{date}"
    
    def __init__(self):
        """初始化爬蟲"""
        self.request_count = 0
        self.download_dir = Path("downloads/fhtrust")
        self.download_dir.mkdir(parents=True, exist_ok=True)
    
    def _random_delay(self):
        """隨機延遲，避免被封鎖"""
        delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        logger.debug(f"Waiting {delay:.2f} seconds...")
        time.sleep(delay)
    
    def get_fund_id(self, etf_code: str) -> Optional[str]:
        """
        獲取 ETF 在復華投信網站的基金代碼
        
        Args:
            etf_code: ETF 代碼 (例如: 00991A)
        
        Returns:
            Optional[str]: 基金代碼，若未找到則返回 None
        """
        fund_id = FHTRUST_ETF_CODES.get(etf_code)
        if not fund_id:
            logger.warning(f"ETF {etf_code} not found in FHTrust code mapping")
        return fund_id
    
    def download_portfolio_excel(
        self, 
        fund_id: str,
        date: str
    ) -> Optional[Path]:
        """
        使用 API 下載投資組合 Excel 文件
        
        Args:
            fund_id: 復華投信基金代碼 (例如: ETF23)
            date: 日期 (YYYY-MM-DD)
        
        Returns:
            Optional[Path]: 下載的文件路徑，失敗時返回 None
        """
        # 轉換日期格式為 YYYYMMDD
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        date_str = date_obj.strftime('%Y%m%d')
        
        api_url = f"{self.BASE_URL}{self.EXCEL_API.format(fund_id=fund_id, date=date_str)}"
        logger.info(f"Downloading portfolio Excel for fund {fund_id} on {date}")
        logger.debug(f"API URL: {api_url}")
        
        downloaded_file = None
        
        try:
            response = requests.get(api_url, timeout=30)
            response.raise_for_status()
            
            # 儲存文件
            filename = f"{fund_id}_{date.replace('-', '')}.xlsx"
            save_path = self.download_dir / filename
            
            with open(save_path, 'wb') as f:
                f.write(response.content)
            
            logger.info(f"Downloaded file: {save_path}")
            downloaded_file = save_path
        
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
            
            # 復華投信的 Excel 格式：
            # - 前 10 行是標題和基金資訊
            # - 第 10 行（index 9）是欄位標題：證券代號、證券名稱、股數、金額、權重(%)
            # - 從第 11 行開始是實際數據
            
            df = pd.read_excel(excel_path, skiprows=10)
            
            logger.debug(f"Excel columns: {df.columns.tolist()}")
            logger.debug(f"Excel shape: {df.shape}")
            
            # 復華投信的欄位名稱
            code_col = '證券代號'
            name_col = '證券名稱'
            shares_col = '股數'
            weight_col = '權重(%)'
            
            # 驗證欄位是否存在
            required_cols = [code_col, name_col, shares_col, weight_col]
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
                        'market_value': 0,  # 可以從「金額」欄位取得，但目前資料庫不需要
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
            etf_code: ETF 代碼 (例如: 00991A)
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
        新增 ETF 與復華投信基金代碼的對照
        
        Args:
            etf_code: ETF 代碼 (例如: 00991A)
            fund_id: 復華投信基金代碼 (例如: ETF23)
        """
        FHTRUST_ETF_CODES[etf_code] = fund_id
        logger.info(f"Added ETF mapping: {etf_code} -> {fund_id}")
    
    def get_all_mappings(self) -> Dict[str, str]:
        """
        獲取所有 ETF 對照表
        
        Returns:
            Dict[str, str]: ETF 代碼對照字典
        """
        return FHTRUST_ETF_CODES.copy()
