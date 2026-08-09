"""
凱基投信 ETF 爬蟲模組

路徑：解析網頁 DOM。凱基的申購買回清單頁面本身不含資料，持股表由
`/Fund/RedemptionVC` 這支 partial view（回傳 HTML 片段，不是 JSON API）載入，
直接 GET/POST 它即可拿到整份清單，無需 Playwright。

資料來源原則是「下載檔案 > DOM > API」。2026-08-09 實測凱基官網**沒有**持股檔案
可下載：「文件下載」（`/Service/DocDownload`）只有公開說明書等文件，申購買回清單
頁面也沒有匯出按鈕，因此 DOM 是唯一路徑。

日期欄位語意（2026-08-09 實測，與摩根 PCF、群益 date1/date2 同款前瞻模式）：
- partial view 內文的「(YYYY/MM/DD)每受益權單位淨資產價值」= 持股基準日（要用這個）
- hidden `#DataDate`（以及查詢框預設值）= **下一營業日**（PCF 適用日），**勿用**。
  實測不帶 queryDate（取最新）時 `DataDate=2026/08/10`，而內文基準日是 2026/08/07。
- 交叉驗算過：該份清單的「基金淨資產價值 ÷ 已發行受益權單位總數」
  = 28,702,559,786 ÷ 3,082,739,000 = 9.31，正好等於它標示的「(2026/08/07)每受益權
  單位淨資產價值 9.31」，可確認括號內日期就是這份持股的基準日。
- `queryDate` 傳非交易日會回 HTTP 500 錯誤頁（不會靜默回退到前一日）；
  傳未來日則等同取最新。
"""

import re
from typing import Any, Dict, List, Tuple

import requests
import urllib3
from bs4 import BeautifulSoup
from loguru import logger

from src.utils import get_user_agent


# 凱基投信 ETF 代碼對照表（值是官網內部 fundID，見申購買回清單頁的 AllFundName）
KGI_ETF_CODES = {
    '00407A': 'J024',  # 主動凱基台灣（2026/06/24 掛牌，首檔不配息主動式 ETF）
    # 凱基旗下其他主動式 ETF 之後可直接在此加入
}


class KGIScraper:
    """凱基投信 (KGI) 爬蟲（申購買回清單 partial view）"""

    BASE_URL = "https://www.kgifund.com.tw"
    LIST_URL = f"{BASE_URL}/Fund/RedemptionList"
    PCF_PARTIAL_URL = f"{BASE_URL}/Fund/RedemptionVC"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': get_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': self.LIST_URL,
        })

    def get_etf_holdings(self, etf_code: str, date: str) -> List[Dict[str, Any]]:
        """獲取 ETF 持股明細

        Args:
            etf_code: ETF 代碼（例如 00407A）
            date: 日期 (YYYY-MM-DD)，解析不到來源日期時才會用到

        Returns:
            List[Dict]: 持股明細列表
        """
        holdings = []
        try:
            fund_id = KGI_ETF_CODES.get(etf_code)
            if not fund_id:
                logger.error(f"KGI: unknown ETF code {etf_code} (not in KGI_ETF_CODES)")
                return []

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            logger.info(f"Fetching KGI holdings for {etf_code} (fundID={fund_id})")

            # 先取一次清單頁：拿 cookie（含 ETF 風險告知），再要 partial view
            self.session.get(self.LIST_URL, timeout=20, verify=False)

            # queryDate 留空＝取最新一份 PCF（其基準日為最近交易日）
            response = self.session.post(
                self.PCF_PARTIAL_URL,
                data={'fundID': fund_id, 'queryDate': ''},
                timeout=20,
                verify=False,
            )

            if response.status_code != 200:
                logger.error(f"KGI: Failed to fetch {etf_code}: HTTP {response.status_code}")
                return []

            soup = BeautifulSoup(response.text, 'html.parser')
            actual_date, source_dated = self._extract_data_date(soup, date)
            holdings = self._parse_html_table(soup, actual_date, etf_code, source_dated)
            logger.info(
                f"Parsed {len(holdings)} holdings for {etf_code} (data date: {actual_date})"
            )

        except Exception as e:
            logger.error(f"Error fetching KGI holdings for {etf_code}: {e}")
            logger.exception(e)

        return holdings

    @staticmethod
    def _extract_data_date(soup: BeautifulSoup, fallback: str) -> Tuple[str, bool]:
        """
        從 partial view 取出凱基標示的持股基準日，取代請求日期。

        錨點是「(YYYY/MM/DD)每受益權單位淨資產價值」——括號內的日期即這份清單所
        依據的收盤日。

        ⚠ 絕不可改用 `#DataDate` 或查詢框的值：那是 PCF 適用日（下一營業日）。
        2026-08-09 實測 `DataDate=2026/08/10`，而基準日是 2026/08/07。

        Args:
            soup: 已解析的 partial view
            fallback: 找不到時使用的日期（請求日期）

        Returns:
            (YYYY-MM-DD, 是否真的取自來源)。第二個值為 False 時代表退回請求日期，
            呼叫端不可標記 source_dated，寫入層的日期錯位防護要繼續生效。
        """
        text = soup.get_text(' ', strip=True)
        found = set(re.findall(
            r'\((20\d{2})/(\d{1,2})/(\d{1,2})\)\s*每受益權單位淨資產價值', text
        ))
        if len(found) != 1:
            logger.warning(
                f"KGI: expected exactly one 每受益權單位淨資產價值-anchored data date, "
                f"got {sorted(found)}; falling back to requested date {fallback}"
            )
            return fallback, False

        y, m, d = found.pop()
        actual = f"{y}-{int(m):02d}-{int(d):02d}"
        if actual != fallback:
            logger.info(f"KGI data date from page: {actual} (requested {fallback})")
        return actual, True

    def _parse_html_table(
        self, soup: BeautifulSoup, date: str, etf_code: str, source_dated: bool = False
    ) -> List[Dict[str, Any]]:
        """解析持股 HTML 表格（表頭：股票代號 / 股票名稱 / 股數 / 權重(%)）"""
        holdings = []
        try:
            table = None
            for t in soup.find_all('table'):
                rows = t.find_all('tr')
                if len(rows) < 2:
                    continue
                head = [c.get_text(' ', strip=True) for c in rows[0].find_all(['th', 'td'])]
                if len(head) >= 4 and head[0] == '股票代號' and head[1] == '股票名稱':
                    table = t
                    break

            if not table:
                logger.warning(
                    f"KGI: stock holdings table not found for {etf_code} (page structure changed?)"
                )
                return []

            for row in table.find_all('tr')[1:]:
                cols = row.find_all(['td', 'th'])
                if len(cols) < 4:
                    continue
                try:
                    code = cols[0].get_text(strip=True)
                    name = cols[1].get_text(strip=True)
                    shares_text = cols[2].get_text(strip=True).replace(',', '')
                    weight_text = cols[3].get_text(strip=True).replace('%', '').replace(',', '')

                    # 只收 4 碼數字的台股代號，順便排除合計列與空列
                    if not (code.isdigit() and len(code) == 4):
                        continue

                    holdings.append({
                        'etf_code': etf_code,
                        'stock_code': code,
                        'stock_name': name,
                        'shares': int(float(shares_text)) if shares_text else 0,
                        'weight': float(weight_text) if weight_text else 0.0,
                        'market_value': 0,  # 凱基申購買回清單沒有揭露個股市值
                        'date': date,
                        'source_dated': source_dated,
                    })
                except Exception as e:
                    logger.debug(f"KGI: error parsing row: {e}")
                    continue

        except Exception as e:
            logger.error(f"KGI: error parsing HTML for {etf_code}: {e}")

        return holdings

    def get_all_mappings(self) -> Dict[str, str]:
        """獲取所有支援的 ETF 代碼"""
        return dict(KGI_ETF_CODES)
