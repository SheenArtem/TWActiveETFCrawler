"""
把證交所已公布、src/trading_calendar.py 還沒收錄的年份的休市日補進清單。

.github/workflows/trading-calendar.yml 每週跑一次，有補才開 PR；也可在本機手動跑。
預設檢查今年與明年（UTC），也可指定年份：
    python scripts/update_trading_calendar.py [年份 ...]

- 已收錄的年份不動；證交所還沒公布（查詢回 0 筆）就什麼都不做。
- 篩選規則與 src/trading_calendar.py 開頭的說明相同：名稱含「開始交易」「最後交易」的列
  有開盤、不收；週末本來就休市、不列；「市場無交易，僅辦理結算交割作業」算休市。
- 證交所回應格式不對時丟例外（非 0 結束），讓 workflow 失敗、GitHub 寄信通知。
- 在 GitHub Actions 裡會把補上的年份寫進 $GITHUB_OUTPUT（years=...），
  有設 PR_BODY_FILE 時把 PR 說明寫進該檔。
"""
import importlib.util
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests

CALENDAR = Path(__file__).resolve().parent.parent / "src" / "trading_calendar.py"
URL = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
OPEN_MARKERS = ("開始交易", "最後交易")  # 證交所清單裡有開盤的日子


def fetch_schedule(year: int) -> list:
    """證交所該年的市場開休市日期；還沒公布時回空串列。每列是 [日期, 名稱, 說明]。"""
    resp = requests.get(URL, params={"response": "json", "date": f"{year}0101"},
                        headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("stat") != "ok" or not isinstance(payload.get("data", []), list):
        raise RuntimeError(f"Unexpected TWSE response for {year}: {str(payload)[:200]}")
    rows = payload.get("data") or []
    if rows and payload.get("fields", [])[:2] != ["日期", "名稱"]:
        raise RuntimeError(f"TWSE schedule fields changed: {payload.get('fields')}")
    outside = [row for row in rows if not str(row[0]).startswith(f"{year}-")]
    if outside:
        raise RuntimeError(f"TWSE schedule for {year} contains other years: {outside[:3]}")
    return rows


def closed_weekdays(rows: list) -> dict:
    """{日期: 名稱}，只留休市的平日。"""
    return {
        row[0]: row[1] for row in rows
        if not any(marker in row[1] for marker in OPEN_MARKERS)
        and date.fromisoformat(row[0]).weekday() < 5
    }


def load_closed_weekdays() -> dict:
    spec = importlib.util.spec_from_file_location("trading_calendar_file", CALENDAR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TWSE_CLOSED_WEEKDAYS


def render_year(year: int, closed: dict) -> str:
    lines = [f"    {year}: frozenset({{"]
    lines += [f'        "{day}",  # {name}' for day, name in sorted(closed.items())]
    lines.append("    }),")
    return "\n".join(lines) + "\n"


def insert_years(text: str, blocks: list) -> str:
    """把新年份的區塊插在 TWSE_CLOSED_WEEKDAYS 最後一個年份之後。"""
    start = text.index("TWSE_CLOSED_WEEKDAYS = {\n")
    closing = text.index("\n}\n", start) + 1
    return text[:closing] + "".join(blocks) + text[closing:]


def pr_body(added: dict) -> str:
    lines = [
        f"證交所已公布 {'、'.join(str(y) for y in added)} 年的市場開休市日期，"
        "由 `scripts/update_trading_calendar.py` 補進 `src/trading_calendar.py`。",
        "",
        f"- 來源：{URL}?response=json&date=<年>0101",
        "- 規則：排除名稱含「開始交易」「最後交易」的列（有開盤）、只留平日；"
        "「市場無交易，僅辦理結算交割作業」算休市。",
        "- `test_duplicate_guard.py` 已在同一個 workflow 裡跑過並通過。",
        "",
        "| 日期 | 名稱 |",
        "| --- | --- |",
    ]
    for year in added:
        lines += [f"| {day} | {name} |" for day, name in sorted(added[year].items())]
    lines += ["", "合併前請對照證交所公告確認。由 `.github/workflows/trading-calendar.yml` 產生。"]
    return "\n".join(lines) + "\n"


def main() -> int:
    this_year = datetime.now(timezone.utc).year
    years = [int(arg) for arg in sys.argv[1:]] or [this_year, this_year + 1]
    known = load_closed_weekdays()

    added = {}
    for year in years:
        if year in known:
            print(f"{year}: already in src/trading_calendar.py")
            continue
        rows = fetch_schedule(year)
        if not rows:
            print(f"{year}: TWSE has not published the schedule yet")
            continue
        closed = closed_weekdays(rows)
        new_year = f"{year}-01-01"
        if date.fromisoformat(new_year).weekday() < 5 and new_year not in closed:
            raise RuntimeError(f"{year}: New Year's Day is missing from the TWSE schedule; check the format")
        added[year] = closed
        print(f"{year}: {len(rows)} rows from TWSE -> {len(closed)} closed weekdays")

    if not added:
        return 0

    text = CALENDAR.read_bytes().decode("utf-8")
    blocks = [render_year(year, closed) for year, closed in sorted(added.items())]
    CALENDAR.write_bytes(insert_years(text, blocks).encode("utf-8"))
    updated = load_closed_weekdays()
    for year, closed in added.items():
        if updated.get(year) != frozenset(closed):
            raise RuntimeError(f"{year}: rewritten src/trading_calendar.py does not match the TWSE list")
    print(f"src/trading_calendar.py updated: {sorted(added)}")

    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(f"years={' '.join(str(y) for y in sorted(added))}\n")
    if os.environ.get("PR_BODY_FILE"):
        Path(os.environ["PR_BODY_FILE"]).write_text(pr_body(dict(sorted(added.items()))), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
