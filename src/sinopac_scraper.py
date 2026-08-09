"""
永豐投信 ETF 爬蟲模組

路徑：解析網頁 DOM（現金申購買回清單頁面 SSR 直出持股表）。

資料來源原則是「下載檔案 > DOM > API」。永豐**確實有** xlsx 下載
（表單送 `op=2`，回 `Pcf-00410A-YYYYMMDD.xlsx`），但 2026-08-09 實測它
**只接受早於今天的日期**：`hDate` 等於或晚於今天時後端回 136 bytes 空白頁，
前端也會擋（`downloadPcf()` 內建 `qdate >= today` 就 alert）。
也就是說檔案路徑永遠拿不到最新一份 PCF，只能拿到再前一個交易日的，
每天都會落後一天。DOM 路徑沒有這個限制，而且頁面自己就標了「資料日期」，
日期可靠度與檔案相同（檔案內文的「資料日期」與網頁逐字一致，已實測），
因此這裡走 DOM。

日期欄位語意（2026-08-09 實測，與摩根 PCF、群益 date1/date2 同款前瞻模式）：
- 頁面「資料日期：YYYY/MM/DD」= 持股基準日（要用這個）
- 查詢框 `qdate` / hidden `hDate` 預設值 = **下一營業日**（PCF 適用日），**勿用**。
  實測 `hDate=2026-08-10` → 資料日期 2026/08/06；`hDate=2026-08-07` → 資料日期 2026/08/06。
- 下載檔名裡的日期也是適用日，不是資料日期（`Pcf-00410A-20260807.xlsx` 內文標 08/06）。
"""

import re
from typing import Any, Dict, List, Tuple

import requests
import urllib3
from bs4 import BeautifulSoup
from loguru import logger

from src.utils import get_user_agent


# 永豐投信 ETF 代碼對照表（值即 PCF 頁面網址最後一段）
SINOPAC_ETF_CODES = {
    '00410A': '00410A',  # 主動永豐科技趨勢（2026/08/03 掛牌）
    # 永豐旗下其他主動式 ETF 之後可直接在此加入
}


class SinoPacScraper:
    """永豐投信 (SinoPac SITC) 爬蟲

    現金申購買回清單頁面純 GET 即可拿到最新一份 PCF，無需 Playwright。
    頁面同時輸出桌機版（`tab_sh-w`，橫向一表到底）與手機版（`tab_sh-m`，
    每檔持股一個縱向小表）兩套表格，解析時只能取桌機版，否則會重複計算。
    """

    PCF_URL = "https://sitc.sinopac.com/SinopacEtfs/Etfs/Pcf/{fund_id}"

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
            etf_code: ETF 代碼（例如 00410A）
            date: 日期 (YYYY-MM-DD)，解析不到來源日期時才會用到

        Returns:
            List[Dict]: 持股明細列表
        """
        holdings = []
        try:
            fund_id = SINOPAC_ETF_CODES.get(etf_code, etf_code)
            url = self.PCF_URL.format(fund_id=fund_id)
            logger.info(f"Fetching SinoPac holdings for {etf_code} from {url}")

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            response = self.session.get(url, timeout=20, verify=False)

            if response.status_code != 200:
                logger.error(f"SinoPac: Failed to fetch {etf_code}: HTTP {response.status_code}")
                return []

            soup = BeautifulSoup(response.text, 'html.parser')
            actual_date, source_dated = self._extract_data_date(soup, date)
            holdings = self._parse_html_table(soup, actual_date, etf_code, source_dated)
            logger.info(
                f"Parsed {len(holdings)} holdings for {etf_code} (data date: {actual_date})"
            )

        except Exception as e:
            logger.error(f"Error fetching SinoPac holdings for {etf_code}: {e}")
            logger.exception(e)

        return holdings

    @staticmethod
    def _extract_data_date(soup: BeautifulSoup, fallback: str) -> Tuple[str, bool]:
        """
        從頁面取出永豐標示的「資料日期」，取代請求日期。

        ⚠ 絕不可改用查詢框 `qdate` / hidden `hDate`：那是 PCF 適用日（下一營業日）。
        2026-08-09 實測其預設值為 2026-08-10，而該頁資料日期是 2026/08/07。

        ⚠ 也**不可**沿用兆豐／台新的「日期＋每基數」錨：永豐頁面的排列剛好相反，
        適用日緊貼在「每申購基數」前面——實測可見文字是
        `（證劵代碼：00410A）2026/08/10 每申購基數之預收申購總價金(元) …`，
        用那個錨會抓到適用日。永豐只能用「資料日期」這個標籤。

        桌機版與手機版各標一次「資料日期」，值相同；出現多個**不同**值時視為改版，
        保守退回請求日期。

        Args:
            soup: 已解析的頁面
            fallback: 找不到時使用的日期（請求日期）

        Returns:
            (YYYY-MM-DD, 是否真的取自來源)。第二個值為 False 時代表退回請求日期，
            呼叫端不可標記 source_dated，寫入層的日期錯位防護要繼續生效。
        """
        text = soup.get_text(' ', strip=True)
        found = set(re.findall(r'資料日期[：:\s]*(20\d{2})[/\-](\d{1,2})[/\-](\d{1,2})', text))
        if len(found) != 1:
            logger.warning(
                f"SinoPac: expected exactly one 資料日期 on page, got {sorted(found)}; "
                f"falling back to requested date {fallback}"
            )
            return fallback, False

        y, m, d = found.pop()
        actual = f"{y}-{int(m):02d}-{int(d):02d}"
        if actual != fallback:
            logger.info(f"SinoPac data date from page: {actual} (requested {fallback})")
        return actual, True

    def _parse_html_table(
        self, soup: BeautifulSoup, date: str, etf_code: str, source_dated: bool = False
    ) -> List[Dict[str, Any]]:
        """解析持股 HTML 表格

        桌機版持股表的第一列是真表頭（證券代碼 / 證券名稱 / 股數 / 佔基金淨資產之權重(%)）；
        手機版每檔一表、第一列是「證券代碼 | 2330」這種 label:value，因此以
        「前兩格分別是『證券代碼』與『證券名稱』」為條件即可只選到桌機版那一張。
        """
        holdings = []
        try:
            table = None
            for t in soup.find_all('table'):
                rows = t.find_all('tr')
                if len(rows) < 2:
                    continue
                head = [c.get_text(' ', strip=True) for c in rows[0].find_all(['th', 'td'])]
                if len(head) >= 4 and head[0] == '證券代碼' and head[1] == '證券名稱':
                    table = t
                    break

            if not table:
                logger.warning(
                    f"SinoPac: stock holdings table not found for {etf_code} (page structure changed?)"
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
                        'market_value': 0,  # 永豐 PCF 頁面沒有揭露個股市值
                        'date': date,
                        'source_dated': source_dated,
                    })
                except Exception as e:
                    logger.debug(f"SinoPac: error parsing row: {e}")
                    continue

        except Exception as e:
            logger.error(f"SinoPac: error parsing HTML for {etf_code}: {e}")

        return holdings

    def get_all_mappings(self) -> Dict[str, str]:
        """獲取所有支援的 ETF 代碼"""
        return dict(SINOPAC_ETF_CODES)
