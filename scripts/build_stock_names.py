"""
建立台股代號 -> 標準中文名稱對照表 (data/stock_names.json)

資料來源：StockAnalyzer 的 TDCC 證券基本資料 universe_tw_full.parquet
（涵蓋上市/上櫃/興櫃普通股 + ETF，含已下市歷史）。

用途：各投信官網提供的成分股名稱格式不一（中文簡稱、含 TWD10 後綴、
甚至全英文），本表以股票代號為主鍵，提供唯一的標準中文簡稱，
供爬蟲輸出時統一顯示名稱。

重新產生（需可存取 StockAnalyzer 目錄）：
    python scripts/build_stock_names.py
"""
import json
from pathlib import Path

import pandas as pd

PARQUET = Path(r"C:\GIT\StockAnalyzer\data_cache\backtest\universe_tw_full.parquet")
OUT = Path(__file__).resolve().parent.parent / "data" / "stock_names.json"

# TDCC 來源把部分罕用字存成 Big5 造字區（PUA）碼位。已用實際成分股
# 原始名稱交叉確認的修正對照如下；其餘無法確認者於下方整筆丟棄。
PUA_FIX = {
    "": "碁",  # 宏碁(2353)/啟碁(6285)/宏碁資訊(6811) 確認
}


def _has_pua(s: str) -> bool:
    """名稱是否仍含造字區或控制字元（無法正確顯示）。"""
    return any(0xE000 <= ord(ch) <= 0xF8FF or ord(ch) < 0x20 for ch in s)


def main():
    df = pd.read_parquet(PARQUET)

    # 只保留普通股與 ETF（排除權證，數量龐大且不會出現在成分股）
    df = df[df["is_common_stock"] | df["is_etf"]].copy()

    # 同一代號可能有多筆（歷史更名/下市）：優先「正常」狀態，再取最新 update_date
    df["_status_rank"] = (df["status"] == "正常").astype(int)
    df = df.sort_values(["_status_rank", "update_date"], ascending=[False, False])
    df = df.drop_duplicates("stock_id", keep="first")

    mapping = {}
    dropped = []
    for _, row in df.iterrows():
        code = str(row.stock_id).strip()
        name = str(row["name"]).strip()
        if not code or not name:
            continue
        for pua, ch in PUA_FIX.items():
            name = name.replace(pua, ch)
        # 仍含無法顯示的造字區字元者丟棄，讓爬蟲原始名稱遞補（避免顯示 box）
        if _has_pua(name):
            dropped.append(code)
            continue
        mapping[code] = name

    if dropped:
        print(f"Dropped {len(dropped)} entries with unresolved PUA chars: {dropped}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=0, sort_keys=True)

    print(f"Wrote {len(mapping)} entries to {OUT}")
    for code in ("2330", "2454", "2317", "2308", "0050"):
        print(f"  {code} -> {mapping.get(code)}")


if __name__ == "__main__":
    main()
