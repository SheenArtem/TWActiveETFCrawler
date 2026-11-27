"""
每日班次的最後一步：有 ETF 連續多個交易日沒有新資料時，讓班次失敗（GitHub 會寄信通知）。

為什麼需要：來源改版或被擋時，scraper 只記一行 ERROR、那一檔當天沒寫入，workflow 照樣是綠的。
2026-11 中信（11-04 起）、聯博（11-11 起）、兆豐（10-27 起）就這樣各停更 2～5 週，期間每個班次
都是 success，網站把舊持股當成現況顯示，直到人工稽核才發現。

判準：每檔 ETF 最新的資料日期，距離「不晚於今天的最近一個交易日」隔了幾個交易日。
- 0：當日已有。1：固定落後一天的來源（第一金、00988A），或當天晚發布，都屬正常。
- 達到 STALE_TRADING_DAYS（預設 3）就算停更；etf_list 裡完全沒有持股的 ETF 也算。
- STALE_IGNORE 列出已知抓不到、不要讓班次變紅的 ETF（逗號分隔）：照樣列出來，但不算失敗。

放在 commit／push 之後跑：班次變紅不影響當天已抓到的資料入庫。「今天」與 main.py 相同，
取執行機器的 datetime.now()（runner 上是 UTC）。

用法：
    python scripts/check_stale_sources.py
"""
import os
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.trading_calendar import last_trading_day, trading_days_between  # noqa: E402

DB_PATH = ROOT / "data" / "etf_holdings.db"


def trading_days_behind(latest: str, today: date) -> int:
    """latest（YYYY-MM-DD）之後、到不晚於 today 的最近一個交易日為止，共有幾個交易日。"""
    return trading_days_between(date.fromisoformat(latest), last_trading_day(today))


def find_stale(db_path, today: date, threshold: int) -> list:
    """
    回傳落後達 threshold 個交易日的 ETF：[(etf_code, 最新資料日期, 落後交易日數)]。

    完全沒有持股的 ETF 以 (etf_code, None, None) 排在最前面，其餘依落後天數由多到少。
    """
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT e.etf_code, MAX(h.date) FROM etf_list e "
            "LEFT JOIN holdings h ON h.etf_code = e.etf_code "
            "WHERE e.etf_code LIKE '%A' GROUP BY e.etf_code ORDER BY e.etf_code"
        ).fetchall()
    finally:
        con.close()

    empty, stale = [], []
    for etf_code, latest in rows:
        if not latest:
            empty.append((etf_code, None, None))
            continue
        behind = trading_days_behind(latest, today)
        if behind >= threshold:
            stale.append((etf_code, latest, behind))
    stale.sort(key=lambda item: (-item[2], item[0]))
    return empty + stale


def run(db_path, today: date, threshold: int, ignore: set) -> int:
    """印出停更清單；有不在 ignore 裡的停更 ETF 時回傳 1，否則 0。"""
    stale = find_stale(db_path, today, threshold)
    reference = last_trading_day(today).isoformat()
    if not stale:
        print(f"所有 ETF 的最新資料距離最近交易日 {reference} 都不到 {threshold} 個交易日")
        return 0

    failing = [item for item in stale if item[0] not in ignore]
    for etf_code, latest, behind in stale:
        detail = "沒有任何持股資料" if latest is None else f"最新資料日期 {latest}，落後 {behind} 個交易日"
        if etf_code in ignore:
            print(f"::warning::{etf_code} {detail}（列在 STALE_IGNORE，不計入失敗）")
        else:
            print(f"::error::{etf_code} {detail}")
    if not failing:
        return 0
    codes = "、".join(item[0] for item in failing)
    print(f"以 {reference} 為準，{len(failing)} 檔 ETF 已連續 {threshold} 個以上交易日沒有新資料：{codes}。"
          f"看這個班次的 log 裡該來源的 ERROR／WARNING，來源指南在 .ai/guides/data-sources.md")
    return 1


def main() -> int:
    threshold = int(os.getenv("STALE_TRADING_DAYS") or "3")
    ignore = {code.strip() for code in (os.getenv("STALE_IGNORE") or "").split(",") if code.strip()}
    return run(DB_PATH, datetime.now().date(), threshold, ignore)


if __name__ == "__main__":
    sys.exit(main())
