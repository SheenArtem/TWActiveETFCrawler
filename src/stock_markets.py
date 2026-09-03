"""
成分股代號慣例與市場判定

`holdings.stock_code` 有兩種形態，整個專案（scraper、名稱正規化、報表）都依賴這個慣例：

- 台股：純數字代號，如 `2330`；ETF 可能是 5～6 碼或帶一個尾碼字母（`00981A`）。
- 海外股票：**照抄來源的 Bloomberg 代號「代號 市場」，中間那個空格與市場後綴一起保留**，
  如 `SNDK US`、`6981 JP`、`009150 KS`、`3308 HK`、`IFX GY`、`300408 CH`。

為什麼海外代號絕不能去掉市場後綴（2026-09-03 實測 00988A 主動統一全球創新）：
39 檔海外持股裡有 5 檔的數字部分剛好等於真實台股代號——
`6997 JP`（NIPPON CHEMI-CON）↔ 6997 博弘、`3308 HK`（中際旭創）↔ 3308 聯德、
`6871 JP`（MICRONICS JAPAN）↔ 6871 新鑫、`5801 JP`（古河電工）↔ 5801 建弘投信、
`4180 JP`（Appier）↔ 4180 安成藥。去掉後綴後 `stock_names.canonical_name()` 會把它們
改名成台股，跨 ETF 的買賣超統計也會把日股與台股加在一起。

單位：「張」（1 張＝1000 股）是台股習慣。海外部位的數值同樣是 股數/1000，
但顯示為「千股」，避免讀者誤以為是台股。
"""
import re
from typing import Optional

# 台股：4～6 碼數字，尾碼可帶一個大寫字母（ETF 如 00981A、00631L）
_TW_CODE_RE = re.compile(r'^\d{4,6}[A-Z]?$')
# 海外：Bloomberg「代號 市場」。代號以字母或數字開頭、可含 . / -（如 BRK/B），市場為兩個大寫字母
_FOREIGN_TICKER_RE = re.compile(r'^[0-9A-Z][0-9A-Z./\-]* [A-Z]{2}$')

TW_MARKET = 'TW'


def normalize_code(raw) -> str:
    """去首尾空白、連續空白壓成一個、轉大寫；None／NaN 回空字串。"""
    text = '' if raw is None else str(raw)
    if text.strip().lower() == 'nan':
        return ''
    return re.sub(r'\s+', ' ', text.strip()).upper()


def market_of(stock_code) -> Optional[str]:
    """
    判定代號屬於哪個市場。

    Returns:
        'TW'：台股純數字代號
        Bloomberg 市場後綴（'US'、'JP'、'KS'、'HK'、'CH'、'GY'…）：海外股票
        None：不是股票代號（表頭文字、空白、合計列、期貨或選擇權描述…），呼叫端應跳過該列
    """
    code = normalize_code(stock_code)
    if not code:
        return None
    if _TW_CODE_RE.match(code):
        return TW_MARKET
    if _FOREIGN_TICKER_RE.match(code):
        return code.rsplit(' ', 1)[1]
    return None


def is_foreign(stock_code) -> bool:
    """是否為海外股票（帶 Bloomberg 市場後綴）。"""
    market = market_of(stock_code)
    return market is not None and market != TW_MARKET


def lot_unit(stock_code) -> str:
    """報表顯示單位：台股「張」，海外「千股」。兩者都是 股數/1000，只差名稱。"""
    return '千股' if is_foreign(stock_code) else '張'
