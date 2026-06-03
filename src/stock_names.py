"""
台股名稱正規化

各投信官網提供的成分股名稱格式不一致（中文簡稱、含 "TWD10" 後綴、
甚至整段英文公司全名），同一支股票在不同 ETF 下顯示不同名稱。

本模組以股票代號為主鍵，將台股名稱統一為標準中文簡稱。
對照表 data/stock_names.json 由 scripts/build_stock_names.py 產生。

非台股項目（期貨、選擇權、現金/存款、海外股等代號不在表中者）
維持原始名稱不變。
"""
import json
from pathlib import Path
from typing import Dict, Optional

from loguru import logger

_NAMES_PATH = Path(__file__).resolve().parent.parent / "data" / "stock_names.json"
_names: Optional[Dict[str, str]] = None


def _load() -> Dict[str, str]:
    """載入對照表（僅載入一次並快取）"""
    global _names
    if _names is None:
        try:
            with open(_NAMES_PATH, "r", encoding="utf-8") as f:
                _names = json.load(f)
            logger.info(f"Loaded {len(_names)} stock name mappings from {_NAMES_PATH.name}")
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Stock name mapping unavailable ({e}); names will not be normalized")
            _names = {}
    return _names


def canonical_name(stock_code: str, fallback: str = "") -> str:
    """
    取得股票代號對應的標準中文名稱。

    Args:
        stock_code: 股票代號（如 "2330"）
        fallback: 查無對照時回傳的名稱（通常為原始名稱）

    Returns:
        標準中文簡稱；若代號不在台股對照表中，回傳 fallback。
    """
    code = (stock_code or "").strip()
    return _load().get(code, fallback)
