"""
復華投信 ETF 爬蟲模組
下載官網投資組合 Excel（`/api/assetsExcel/{fund_id}/{YYYYMMDD}`）並解析持股與實際資料日期。
"""
import re
import requests
import time
import random
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path
import pandas as pd
from loguru import logger

from .config import (
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX
)
from .stock_markets import market_of, normalize_code


# 復華投信 ETF 基金代碼對照表
FHTRUST_ETF_CODES = {
    '00991A': 'ETF23',  # 復華台灣未來50主動式ETF基金
    # 未來可以新增其他復華投信 ETF
}


class FHTrustScraper:
    """復華投信網站 ETF 爬蟲（下載投資組合 Excel）"""

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
            Optional[Path]: 下載的文件路徑，未發布或失敗時返回 None
        """
        # 轉換日期格式為 YYYYMMDD
        date_obj = datetime.strptime(date, '%Y-%m-%d')
        date_str = date_obj.strftime('%Y%m%d')

        api_url = f"{self.BASE_URL}{self.EXCEL_API.format(fund_id=fund_id, date=date_str)}"
        logger.info(f"Downloading portfolio Excel for fund {fund_id} on {date}")
        logger.debug(f"API URL: {api_url}")

        try:
            response = requests.get(api_url, timeout=30)
            response.raise_for_status()

            # 非交易日或當日尚未發布時，端點回 HTTP 200 但內容為純文字 '查無資料'（非 ZIP/xlsx）
            if not response.content or response.content[:2] != b'PK':
                preview = (response.content or b'')[:80].decode('utf-8', errors='replace').strip()
                logger.warning(
                    f"FHTrust {fund_id} on {date}: response is not an xlsx file "
                    f"({len(response.content or b'')} bytes: {preview!r}); data likely not published yet"
                )
                return None

            # 儲存文件
            filename = f"{fund_id}_{date.replace('-', '')}.xlsx"
            save_path = self.download_dir / filename

            with open(save_path, 'wb') as f:
                f.write(response.content)

            logger.info(f"Downloaded file: {save_path}")
            return save_path

        except Exception as e:
            logger.error(f"Error downloading Excel: {e}")
            logger.exception(e)
            return None

    @staticmethod
    def _extract_data_date(excel_path: Path, fallback: str) -> Tuple[str, bool]:
        """
        從復華投資組合 Excel 表頭取出「日期: YYYY/MM/DD」實際資料日期。

        實測第 3 列（index 2）為 ['日期: 2026/10/22']。掃描前 12 列含「日期」的列：
        若唯一解析出一個西元日期，回傳 (YYYY-MM-DD, True)；若無日期或出現多個不同日期，
        保守退回 fallback 且回傳 False，讓寫入層重複防護維持生效。
        """
        try:
            head = pd.read_excel(excel_path, header=None, nrows=12, engine='openpyxl')
        except Exception as e:
            logger.warning(f"FHTrust: cannot read Excel header to find data date: {e}")
            return fallback, False

        found = set()
        for _, row in head.iterrows():
            values = [str(v).strip() for v in row.tolist() if pd.notna(v) and str(v).strip()]
            if not any('日期' in v for v in values):
                continue
            for value in values:
                for m in re.finditer(r'(20\d{2})[/\-年](\d{1,2})[/\-月](\d{1,2})', value):
                    iso = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                    try:
                        datetime.strptime(iso, '%Y-%m-%d')
                        found.add(iso)
                    except ValueError:
                        continue

        if len(found) == 1:
            actual = next(iter(found))
            if actual != fallback:
                logger.info(f"FHTrust data date from Excel: {actual} (requested {fallback})")
            return actual, True
        if len(found) > 1:
            logger.warning(
                f"FHTrust: conflicting dates {sorted(found)} in Excel header; "
                f"falling back to {fallback} without source_dated"
            )
        else:
            logger.warning(
                f"FHTrust: no 日期 found in Excel header; "
                f"falling back to {fallback} without source_dated"
            )
        return fallback, False

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
            date: 請求日期 (YYYY-MM-DD)，僅作表頭無日期時的備援

        Returns:
            List[Dict]: 持股明細列表
        """
        holdings = []

        try:
            logger.info(f"Parsing Excel file: {excel_path}")
            actual_date, source_dated = self._extract_data_date(excel_path, date)

            # 復華投信的 Excel 格式：
            # - 前段為基金名稱、日期: YYYY/MM/DD、淨值與單位數
            # - 欄位標題列含：證券代號、證券名稱、股數、金額、權重(%)（通常在第 11 列，index 10）
            # 動態尋找「證券代號」表頭列，避免上方增減列數導致位移。
            raw_df = pd.read_excel(excel_path, header=None, engine='openpyxl')
            header_idx = None
            for i, r in raw_df.iterrows():
                vals = [str(v).strip() for v in r.tolist() if pd.notna(v)]
                if '證券代號' in vals:
                    header_idx = i
                    break

            if header_idx is None:
                logger.error(f"Missing header row containing '證券代號' in {excel_path}")
                return []

            headers = [
                str(v).strip() if pd.notna(v) else ''
                for v in raw_df.iloc[header_idx].tolist()
            ]
            df = raw_df.iloc[header_idx + 1:].copy()
            df.columns = headers

            logger.debug(f"Excel columns (row {header_idx}): {df.columns.tolist()}")
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

            logger.debug("Found all required columns")

            # 解析每一行
            for idx, row in df.iterrows():
                try:
                    stock_code = normalize_code(row[code_col])
                    if market_of(stock_code) is None:
                        if stock_code and stock_code != code_col:
                            logger.debug(f"Skipping non-holding code: {stock_code}")
                        continue

                    stock_name = '' if pd.isna(row[name_col]) else str(row[name_col]).strip()

                    holding = {
                        'etf_code': etf_code,
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'weight': self._parse_percentage(row[weight_col]),
                        'shares': self._parse_number(row[shares_col]),
                        'market_value': 0,  # 可以從「金額」欄位取得，但目前資料庫不需要
                        'date': actual_date,
                        'source_dated': source_dated,
                    }

                    holdings.append(holding)

                except Exception as e:
                    logger.debug(f"Error parsing row {idx}: {e}")
                    continue

            logger.info(
                f"Parsed {len(holdings)} holdings from Excel on {actual_date} "
                f"(source_dated={source_dated})"
            )

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
            logger.warning(f"No portfolio Excel available for {etf_code} on {date}")
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
            except Exception:
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
            except Exception:
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
