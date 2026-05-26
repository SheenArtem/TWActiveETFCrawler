"""
國泰投信 ETF 爬蟲模組
透過官網內部 JSON API GetIndexStockWeights 抓取持股權重。

注意：此 endpoint 只回傳股票代號、名稱、權重(%)，未提供持股股數，
因此 shares 一律寫 0。其它欄位（市值）也無法取得。
若日後改用 PCF Excel (DownloadETFWeightExcel / DownloadBuySaleExcel)
取得股數，再來重構此模組。
"""
import random
import time
from typing import List, Dict, Any, Optional

import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import REQUEST_DELAY_MIN, REQUEST_DELAY_MAX, MAX_RETRIES


# 國泰投信 ETF 代碼對照表
# key = 證交所代碼 (00400A)
# value = 國泰自家 FundCode (例如 EA)
# 查法：呼叫 https://cwapi.cathaysite.com.tw/api/ETF/GetETFList
CATHAY_ETF_CODES = {
    '00400A': 'EA',  # 主動國泰動能高息
}

API_BASE = 'https://cwapi.cathaysite.com.tw'
WEIGHTS_ENDPOINT = '/api/ETF/GetIndexStockWeights'


class CathayScraper:
    """國泰投信網站 ETF 爬蟲"""

    def __init__(self):
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session

    def _headers(self) -> Dict[str, str]:
        return {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ),
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.8',
            'Origin': 'https://www.cathaysite.com.tw',
            'Referer': 'https://www.cathaysite.com.tw/',
        }

    def _random_delay(self):
        time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

    def get_all_mappings(self) -> Dict[str, str]:
        return CATHAY_ETF_CODES.copy()

    def _get_fund_code(self, etf_code: str) -> Optional[str]:
        fc = CATHAY_ETF_CODES.get(etf_code)
        if not fc:
            logger.warning(f"Cathay: ETF {etf_code} not in mapping")
        return fc

    def get_etf_holdings(self, etf_code: str, date: str) -> List[Dict[str, Any]]:
        """
        傳入 date 僅做為呼叫端期望日期；實際以 API 回傳的 result.date 為準。
        """
        fund_code = self._get_fund_code(etf_code)
        if not fund_code:
            return []

        url = f"{API_BASE}{WEIGHTS_ENDPOINT}?FundCode={fund_code}"
        logger.info(f"Cathay: fetching {etf_code} (FundCode={fund_code})")
        self._random_delay()
        try:
            r = self.session.get(url, headers=self._headers(), timeout=30, verify=False)
            r.raise_for_status()
            data = r.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Cathay: request failed for {etf_code}: {e}")
            return []
        except ValueError as e:
            logger.error(f"Cathay: JSON parse failed for {etf_code}: {e}")
            return []

        if not data.get('success'):
            logger.warning(f"Cathay: API returned non-success for {etf_code}: {data.get('returnMessage')}")
            return []

        result = data.get('result') or {}
        raw_date = result.get('date') or ''
        # API 日期格式 "2026/05/26" -> "2026-05-26"
        if '/' in raw_date:
            actual_date = raw_date.replace('/', '-')
        else:
            actual_date = date

        stock_weights = result.get('stockWeights') or []
        holdings = []
        for row in stock_weights:
            stock_code = (row.get('stockCode') or '').strip()
            stock_name = (row.get('stockName') or '').strip()
            try:
                weight = float(str(row.get('weights') or '0').replace('%', '').replace(',', ''))
            except (TypeError, ValueError):
                weight = 0.0
            if not stock_code:
                continue
            holdings.append({
                'etf_code': etf_code,
                'stock_code': stock_code,
                'stock_name': stock_name,
                'shares': 0,         # API 未提供
                'market_value': 0,   # API 未提供
                'weight': weight,
                'date': actual_date,
            })

        logger.info(f"Cathay: parsed {len(holdings)} holdings for {etf_code} on {actual_date}")
        return holdings
