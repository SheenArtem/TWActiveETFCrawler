"""
兆豐投信 ETF 爬蟲模組

路徑：解析網頁 DOM。兆豐的申購買回清單頁（`etf/trade_pcf.aspx`）是 ASP.NET
WebForms，預設顯示清單裡的第一檔基金，要換基金必須帶 `__VIEWSTATE` 回送 postback，
因此流程是「GET 取 VIEWSTATE → POST 指定 fund_id」兩步，純 requests 即可，無需 Playwright。

資料來源原則是「下載檔案 > DOM > API」。2026-08-09 實測兆豐官網**沒有**持股檔案可下載：
「下載專區」（`service/download.aspx`）只有公開說明書、月報等文件，申購買回清單頁面
也沒有匯出按鈕，因此 DOM 是唯一路徑。

日期欄位語意（2026-08-09 實測，與台新完全同款）：
- 頁面把持股基準日黏在金額欄位的文字前面：「YYYY/MM/DD 每基數實際申購總價金(元)」，
  以「日期＋每基數」為錨（台新是同一種樣態，見 tsit_scraper）。
- 頁面最顯眼的「查詢日期」是 **PCF 適用日（下一營業日）**，**勿用**。實測預設值
  2026/08/10，而該份清單的基準日是 2026/08/07；把 `qdt` 指定成 2026/08/07 查詢時，
  基準日會變成 2026/08/06，可證實「查詢日期」與資料日期整整差一個交易日。
"""

import re
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3
from bs4 import BeautifulSoup
from loguru import logger

from src.utils import get_user_agent


# 兆豐投信 ETF 代碼對照表（值是 trade_pcf.aspx 上 fund_id 下拉選單的 value）
MEGA_ETF_CODES = {
    '00996A': '23',  # 兆豐台灣豐收主動式ETF基金（2026/03/25 掛牌）
    # 兆豐旗下其他主動式 ETF 之後可直接在此加入；value 取自該頁 fund_id 選項，
    # 必須用基金全名核對，不要掃號猜。
}


class MegaFundsScraper:
    """兆豐投信 (Mega Funds) 爬蟲（申購買回清單 WebForms postback）"""

    PCF_URL = "https://www.megafunds.com.tw/MEGA/etf/trade_pcf.aspx"
    # WebForms 控件名稱前綴
    CTL_PREFIX = "ctl00$ContentPlaceHolder1$"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': get_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': self.PCF_URL,
        })

    def get_etf_holdings(self, etf_code: str, date: str) -> List[Dict[str, Any]]:
        """獲取 ETF 持股明細

        Args:
            etf_code: ETF 代碼（例如 00996A）
            date: 日期 (YYYY-MM-DD)，解析不到來源日期時才會用到

        Returns:
            List[Dict]: 持股明細列表
        """
        holdings = []
        try:
            fund_id = MEGA_ETF_CODES.get(etf_code)
            if not fund_id:
                logger.error(f"Mega: unknown ETF code {etf_code} (not in MEGA_ETF_CODES)")
                return []

            soup = self._fetch_fund_page(etf_code, fund_id)
            if soup is None:
                return []

            actual_date, source_dated = self._extract_data_date(soup, date)
            holdings = self._parse_html_table(soup, actual_date, etf_code, source_dated)
            logger.info(
                f"Parsed {len(holdings)} holdings for {etf_code} (data date: {actual_date})"
            )

        except Exception as e:
            logger.error(f"Error fetching Mega holdings for {etf_code}: {e}")
            logger.exception(e)

        return holdings

    def _fetch_fund_page(self, etf_code: str, fund_id: str) -> Optional[BeautifulSoup]:
        """GET 取 VIEWSTATE，再 POST 切換到指定基金

        只回送頁面上實際存在的 hidden 欄位。多送 `__EVENTTARGET` 之類頁面沒有的欄位
        會讓 ASP.NET 把請求丟回首頁（2026-08-09 實測），拿到的頁面就沒有持股表。
        """
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.info(f"Fetching Mega holdings for {etf_code} (fund_id={fund_id})")

        first = self.session.get(self.PCF_URL, timeout=20, verify=False)
        if first.status_code != 200:
            logger.error(f"Mega: Failed to open PCF page: HTTP {first.status_code}")
            return None

        first_soup = BeautifulSoup(first.text, 'html.parser')

        def hidden(name: str) -> str:
            el = first_soup.find('input', {'name': name})
            return el.get('value', '') if el else ''

        payload = {
            '__VIEWSTATE': hidden('__VIEWSTATE'),
            '__VIEWSTATEGENERATOR': hidden('__VIEWSTATEGENERATOR'),
            '__VIEWSTATEENCRYPTED': '',
            f'{self.CTL_PREFIX}category_id': '',
            f'{self.CTL_PREFIX}fund_id': fund_id,
            # qdt（查詢日期）留空＝取最新一份 PCF，其基準日為最近交易日
            f'{self.CTL_PREFIX}qdt': '',
            f'{self.CTL_PREFIX}button1': '查 詢',
        }

        resp = self.session.post(self.PCF_URL, data=payload, timeout=20, verify=False)
        if resp.status_code != 200:
            logger.error(f"Mega: postback failed for {etf_code}: HTTP {resp.status_code}")
            return None

        soup = BeautifulSoup(resp.text, 'html.parser')

        # 確認 postback 真的切到目標基金：頁面標題會寫「（股票代號：00996A 簡稱：…）」。
        # 沒切到就回傳 None，而不是拿別檔的持股當成這一檔寫進 DB。
        text = soup.get_text(' ', strip=True)
        if not re.search(rf'股票代號[：:\s]*{re.escape(etf_code)}\b', text):
            shown = re.search(r'股票代號[：:\s]*([\dA-Z]+)', text)
            logger.error(
                f"Mega: postback did not switch to {etf_code} "
                f"(page shows {shown.group(1) if shown else 'unknown'}); aborting"
            )
            return None

        return soup

    @staticmethod
    def _extract_data_date(soup: BeautifulSoup, fallback: str) -> Tuple[str, bool]:
        """
        從頁面取出兆豐標示的持股基準日，取代請求日期。

        真資料日期黏在金額欄位文字前面：「2026/08/07 每基數實際申購總價金(元)」，
        以「日期＋每基數」為錨（與台新同款）。頁面上這類日期應一致，出現多個不同值
        時視為改版，保守退回。

        ⚠ 絕不可改用頁面上的「查詢日期」：那是 PCF 適用日（下一營業日）。

        Args:
            soup: 已解析的頁面
            fallback: 找不到時使用的日期（請求日期）

        Returns:
            (YYYY-MM-DD, 是否真的取自來源)。第二個值為 False 時代表退回請求日期，
            呼叫端不可標記 source_dated，寫入層的日期錯位防護要繼續生效。
        """
        text = soup.get_text(' ', strip=True)
        found = set(re.findall(r'(20\d{2}/\d{1,2}/\d{1,2})(?=\s*每基數)', text))
        if len(found) != 1:
            logger.warning(
                f"Mega: expected exactly one 每基數-anchored data date, got {sorted(found)}; "
                f"falling back to requested date {fallback}"
            )
            return fallback, False

        y, m, d = found.pop().split('/')
        actual = f"{y}-{int(m):02d}-{int(d):02d}"
        if actual != fallback:
            logger.info(f"Mega data date from page: {actual} (requested {fallback})")
        return actual, True

    def _parse_html_table(
        self, soup: BeautifulSoup, date: str, etf_code: str, source_dated: bool = False
    ) -> List[Dict[str, Any]]:
        """解析持股 HTML 表格

        股票持股表是 `table.table-stock`（股票代號 / 股票名稱 / 股數 / 持股權重）；
        同頁另有 `table.table-futures`（期貨，用「口數」）——00996A 有期貨避險部位，
        靠 class 區分即可，不會混進來。
        """
        holdings = []
        try:
            table = soup.find('table', class_='table-stock')
            if not table:
                logger.warning(
                    f"Mega: stock holdings table not found for {etf_code} (page structure changed?)"
                )
                return []

            for row in table.find_all('tr'):
                cols = row.find_all(['td', 'th'])
                if len(cols) < 4:
                    continue
                try:
                    code = cols[0].get_text(strip=True)
                    name = cols[1].get_text(strip=True)
                    shares_text = cols[2].get_text(strip=True).replace(',', '')
                    weight_text = cols[3].get_text(strip=True).replace('%', '').replace(',', '')

                    # 只收 4 碼數字的台股代號，順便排除表頭、合計列與空列
                    if not (code.isdigit() and len(code) == 4):
                        continue

                    holdings.append({
                        'etf_code': etf_code,
                        'stock_code': code,
                        'stock_name': name,
                        'shares': int(float(shares_text)) if shares_text else 0,
                        'weight': float(weight_text) if weight_text else 0.0,
                        'market_value': 0,  # 兆豐申購買回清單沒有揭露個股市值
                        'date': date,
                        'source_dated': source_dated,
                    })
                except Exception as e:
                    logger.debug(f"Mega: error parsing row: {e}")
                    continue

        except Exception as e:
            logger.error(f"Mega: error parsing HTML for {etf_code}: {e}")

        return holdings

    def get_all_mappings(self) -> Dict[str, str]:
        """獲取所有支援的 ETF 代碼"""
        return dict(MEGA_ETF_CODES)
