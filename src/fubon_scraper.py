
import re
import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Tuple
from loguru import logger
from src.utils import get_user_agent
import urllib3


class FubonScraper:
    """富邦投信 (Fubon) 爬蟲

    富邦 ETF 官網「基金資產」頁面直接以 SSR 渲染完整持股表，純 GET 即可，
    無需 ASP.NET postback。表頭欄位：股票代號 / 股票名稱 / 股數 / 金額 / 權重(%)。
    頁面下方雖有「下載」按鈕，但那是 __doPostBack 表單送出，反而較脆弱，故走 HTML 表格。
    """

    ASSETS_URL = "https://websys.fsit.com.tw/FubonETF/Fund/Assets.aspx?stkId={etf_code}"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': get_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        })

    def get_etf_holdings(self, etf_code: str, date: str) -> List[Dict[str, Any]]:
        """獲取 ETF 持股明細

        Args:
            etf_code: ETF 代碼 (例如: 00405A)
            date: 日期 (YYYY-MM-DD)，用於存入 DB 的日期欄位

        Returns:
            List[Dict]: 持股明細列表
        """
        holdings = []
        try:
            url = self.ASSETS_URL.format(etf_code=etf_code)
            logger.info(f"Fetching Fubon holdings for {etf_code} from {url}")

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = self.session.get(url, timeout=15, verify=False)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                actual_date, source_dated = self._extract_data_date(soup, date)
                holdings = self._parse_html_table(soup, actual_date, etf_code, source_dated)
                logger.info(f"Parsed {len(holdings)} holdings for {etf_code} (data date: {actual_date})")
            else:
                logger.error(f"Fubon: Failed to fetch {etf_code}: HTTP {response.status_code}")

        except Exception as e:
            logger.error(f"Error fetching Fubon holdings for {etf_code}: {e}")
            logger.exception(e)

        return holdings

    @staticmethod
    def _extract_data_date(soup: BeautifulSoup, fallback: str) -> Tuple[str, bool]:
        """
        從頁面取出富邦標示的「資料日期」，取代請求日期。

        頁面上有「資料日期：2026/08/04」。富邦當日資料的發布時間不固定，
        盤中抓到的可能仍是前一交易日（2026-08-05 16:44 實測已有當日），
        沿用請求日期就會把前一日內容標成當日。

        Args:
            soup: 已解析的頁面
            fallback: 找不到時使用的日期（請求日期）

        Returns:
            (YYYY-MM-DD, 是否真的取自來源)。第二個值為 False 時代表退回請求日期，
            呼叫端不可標記 source_dated，寫入層的日期錯位防護要繼續生效。
        """
        match = re.search(
            r'資料日期[：:\s]*(20\d{2})[/\-年](\d{1,2})[/\-月](\d{1,2})',
            soup.get_text(' ', strip=True),
        )
        if not match:
            logger.warning(
                f"Fubon: 資料日期 not found on page; falling back to requested date {fallback}"
            )
            return fallback, False

        y, m, d = match.groups()
        actual = f"{y}-{int(m):02d}-{int(d):02d}"
        if actual != fallback:
            logger.info(f"Fubon data date from page: {actual} (requested {fallback})")
        return actual, True

    def _parse_html_table(
        self, soup: BeautifulSoup, date: str, etf_code: str, source_dated: bool = False
    ) -> List[Dict[str, Any]]:
        """解析持股 HTML 表格

        定位表頭含「股數」與「權重」的股票表（排除含「口數」的期貨表、無這些欄位的資產彙總表）。
        資料列欄位：代碼 / 名稱 / 股數 / 金額(市值) / 權重(%)。
        """
        holdings = []
        try:
            table = None
            for t in soup.find_all('table'):
                header_text = ' '.join(td.get_text(strip=True) for td in t.find_all('td', class_='tac')[:6])
                if '股數' in header_text and '權重' in header_text and '口數' not in header_text:
                    table = t
                    break

            if not table:
                logger.warning(f"Fubon: stock holdings table not found for {etf_code} (page structure changed?)")
                return []

            for row in table.find_all('tr'):
                cols = row.find_all('td')
                if len(cols) < 5:
                    continue
                try:
                    code = cols[0].text.strip()
                    name = cols[1].text.strip()
                    shares_text = cols[2].text.strip().replace(',', '')
                    market_value_text = cols[3].text.strip().replace(',', '')
                    weight_text = cols[4].text.strip().replace('%', '')

                    # 跳過表頭列（代號欄是「股票代號」而非數字）
                    if not code or not code[0].isdigit():
                        continue

                    shares = int(float(shares_text)) if shares_text else 0
                    market_value = int(float(market_value_text)) if market_value_text else 0
                    weight = float(weight_text) if weight_text else 0.0

                    holdings.append({
                        'etf_code': etf_code,
                        'stock_code': code,
                        'stock_name': name,
                        'shares': shares,
                        'weight': weight,
                        'market_value': market_value,
                        'date': date,
                        'source_dated': source_dated
                    })
                except Exception as e:
                    logger.debug(f"Fubon: error parsing row: {e}")
                    continue

        except Exception as e:
            logger.error(f"Fubon: error parsing HTML for {etf_code}: {e}")

        return holdings

    def get_all_mappings(self) -> Dict[str, str]:
        """獲取所有支援的 ETF 代碼

        00405A 主動富邦台灣龍躍 (2026/06/09 掛牌)。
        富邦旗下其他主動式 ETF 之後可直接在此加入。
        """
        return {
            "00405A": "00405A"
        }
