"""
ETF 中文名稱對照表

名稱一律採用**證交所官方簡稱**，來源為 TWSE OpenData STOCK_DAY_ALL 的 Name 欄位
（與 `src/etf_market_data.py` 取市場資料時拿到的名稱同源，因此網頁上「市場資料」
與「持股明細」兩區塊顯示的名稱會一致）。

新增 ETF 時的取得方式：
    python -c "import sys; sys.path.insert(0,'.'); from src.etf_market_data import ETFMarketDataFetcher; \
               d=ETFMarketDataFetcher().fetch_stock_day_all(); print(d['00406A']['name'])"

不要自己翻譯或簡寫，避免與網頁市場資料區塊顯示不一致。
"""
from typing import Dict

# ETF 代號 -> 證交所官方中文簡稱（2026-08-05 取自 TWSE OpenData）
ETF_NAMES: Dict[str, str] = {
    # --- 009xxA 系列 ---
    '00980A': '主動野村臺灣優選',
    '00981A': '主動統一台股增長',
    '00982A': '主動群益台灣強棒',
    '00984A': '主動安聯台灣高息',
    '00985A': '主動野村台灣50',
    '00987A': '主動台新優勢成長',
    '00991A': '主動復華未來50',
    '00992A': '主動群益科技創新',
    '00993A': '主動安聯台灣',
    '00994A': '主動第一金台股優',
    '00995A': '主動中信台灣卓越',
    '00996A': '主動兆豐台灣豐收',
    '00999A': '主動野村臺灣高息',
    # --- 004xxA 系列 ---
    '00400A': '主動國泰動能高息',
    '00401A': '主動摩根台灣鑫收',
    '00403A': '主動統一升級50',
    '00404A': '主動聯博動能50',
    '00405A': '主動富邦台灣龍耀',
    '00406A': '主動中信台灣收益',
    '00407A': '主動凱基台灣',
    '00408A': '主動第一金優股息',
    '00410A': '主動永豐科技趨勢',
}


def get_etf_name(etf_code: str, fallback: str = None) -> str:
    """
    取得 ETF 中文名稱

    Args:
        etf_code: ETF 代碼（例如 00406A）
        fallback: 查不到時使用的名稱；未指定則回傳代碼本身

    Returns:
        str: 中文名稱，查不到時回傳 fallback 或 etf_code
    """
    return ETF_NAMES.get(etf_code) or fallback or etf_code
