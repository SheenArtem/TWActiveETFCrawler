"""
從連得到兆豐官網的機器補 00996A 的持股，並重生受影響的報表。

為什麼需要：兆豐前端的 Akamai 依來源 IP 擋 GitHub runner（整個網域 403），每日班次抓不到；
台灣的一般網路（開發機）正常。這支給本機排程每天跑（scripts/local_megafunds_job.ps1），
也可以手動跑。細節見 .ai/guides/data-sources.md「兆豐：GitHub runner 被 Akamai 依來源 IP 擋」。

做什麼：
1. 抓最新一份，看來源已經到哪個基準日；DB 最後一個資料日期之後、到那一天為止的交易日都要補。
2. 最新那天用剛抓的；更早的逐日查（qdt＝下一個交易日）。頁面自己標的基準日必須等於要補的那一天。
3. 寫入 DB（Database.insert_holdings，來源日期）。
4. 重生這些日期起已發布的報表：只有 00996A 用新資料，其他 ETF 固定在發布當時的資料日期
   （scripts/pinned_reports.py）。還沒發布的那一天不用處理，下一個每日班次會帶到。

只改工作目錄裡的 data/、docs/、reports/，不做任何 git 操作。

用法：
    python scripts/backfill_megafunds.py            # 補到來源最新
    python scripts/backfill_megafunds.py --dry-run  # 只看要補哪幾天，不寫
結束碼：0 = 補完或沒有要補的；1 = 有日子補不到或報表核對沒過（已寫入的部分照樣留著，訊息會講明）。
"""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from loguru import logger  # noqa: E402

import pinned_reports  # noqa: E402
from src.database import Database  # noqa: E402
from src.trading_calendar import is_trading_day, last_trading_day  # noqa: E402

ETF = "00996A"
# 一次最多補幾個交易日。平常是 1 天；電腦關機幾週後第一次跑會多一些。超過這個數字多半是 DB 或
# 日期出了別的問題，不要對著兆豐連發上百次查詢，改由人看過再用 --max-days 放寬。
MAX_DAYS = 40


def trading_days_after(start: str, end: str) -> List[str]:
    """start 之後（不含）到 end（含）的交易日。"""
    day, last, days = date.fromisoformat(start) + timedelta(days=1), date.fromisoformat(end), []
    while day <= last:
        if is_trading_day(day):
            days.append(day.isoformat())
        day += timedelta(days=1)
    return days


def run(scraper, db_path: Path, docs_dir: Path, reports_dir: Path, today: date,
        dry_run: bool = False, max_days: int = MAX_DAYS, pause_seconds: float = 2.0,
        say=print) -> dict:
    """
    補 00996A 到來源最新的基準日，並重生受影響的已發布報表。

    Args:
        scraper: 有 get_etf_holdings(etf, 請求日期) 與 get_holdings_for_data_date(etf, 基準日) 的物件
            （MegaFundsScraper；測試用替身）
        today: 今天的日期（請求日期，也用來擋掉晚於最近交易日的基準日）
        pause_seconds: 逐日查詢之間停幾秒

    Returns:
        {etf, last_in_db, source_latest, inserted, missing, reports, ok}；ok=False 時 message 講原因。
    """
    result = {"etf": ETF, "last_in_db": None, "source_latest": None, "inserted": [], "missing": [],
              "reports": [], "ok": False}

    def stop(message: str, ok: bool = False) -> dict:
        result.update(ok=ok, message=message)
        say(message)
        return result

    db = Database(str(db_path))
    last_in_db = db.get_latest_date(ETF)
    result["last_in_db"] = last_in_db
    if not last_in_db:
        return stop(f"{ETF} 在 DB 裡沒有任何資料，不知道從哪一天補起")

    latest = scraper.get_etf_holdings(ETF, today.isoformat())
    if not latest or not all(row.get("source_dated") for row in latest):
        return stop("抓不到兆豐最新一份清單（這台機器連不到兆豐，或頁面改版）；什麼都沒寫")
    source_latest = latest[0]["date"]
    result["source_latest"] = source_latest
    limit = last_trading_day(today).isoformat()
    if source_latest > limit or not is_trading_day(date.fromisoformat(source_latest)):
        return stop(f"兆豐頁面標的基準日是 {source_latest}，不是不晚於 {limit} 的交易日；什麼都沒寫")

    todo = trading_days_after(last_in_db, source_latest)
    say(f"DB 最後一天 {last_in_db}；來源最新 {source_latest}；要補 {len(todo)} 天：{todo}")
    if not todo:
        return stop("沒有要補的資料", ok=True)
    if len(todo) > max_days:
        return stop(f"要補 {len(todo)} 天，超過上限 {max_days} 天；確認 DB 沒問題後用 --max-days 放寬。什麼都沒寫")

    snapshots = {}
    for day in todo:
        if day == source_latest:
            rows = latest
        else:
            time.sleep(pause_seconds)
            rows = scraper.get_holdings_for_data_date(ETF, day)
        if rows and all(row.get("source_dated") and row.get("date") == day for row in rows):
            snapshots[day] = rows
            say(f"  {day}: {len(rows)} 檔，權重合計 {sum(r['weight'] for r in rows):.2f}%")
        else:
            result["missing"].append(day)
            say(f"  {day}: 來源查不到這一天（或頁面標的基準日不是這一天），沒有補")
    if dry_run:
        return stop("--dry-run：沒有寫入", ok=not result["missing"])

    for day, rows in snapshots.items():
        db.insert_holdings(rows)
        result["inserted"].append(day)
    if not result["inserted"]:
        return stop("要補的日子來源都查不到；什麼都沒寫")

    report_dates = [d for d in pinned_reports.published_dates(docs_dir) if d >= result["inserted"][0]]
    outcomes = pinned_reports.regenerate(report_dates, [ETF], db_path=db_path, docs_dir=docs_dir,
                                         reports_dir=reports_dir) if report_dates else []
    for outcome in outcomes:
        say(f"  報表 {outcome['date']}: {outcome['status']}")
        for line in outcome["notes"] + [f"!! {p}" for p in outcome["problems"]]:
            say(f"      {line}")
    result["reports"] = [{"date": o["date"], "status": o["status"]} for o in outcomes]
    if not report_dates:
        say("這幾天的報表都還沒發布，下一個每日班次會帶到")
    reports_ok = all(o["status"] in ("written", "unchanged") for o in outcomes)
    if result["missing"]:
        return stop(f"已補 {result['inserted']}；補不到的日子：{result['missing']}")
    if not reports_ok:
        return stop(f"已補 {result['inserted']}，但有報表沒通過核對、沒有重生（見上）")
    return stop(f"已補 {result['inserted']}，重生 {sum(o['status'] == 'written' for o in outcomes)} 份報表", ok=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="本機回補兆豐 00996A 並重生受影響的報表")
    parser.add_argument("--dry-run", action="store_true", help="只列出要補的日期，不寫 DB 也不動報表")
    parser.add_argument("--max-days", type=int, default=MAX_DAYS, help=f"一次最多補幾個交易日（預設 {MAX_DAYS}）")
    parser.add_argument("--result-file", help="把結果寫成 JSON（排程用來組 commit 訊息）")
    parser.add_argument("--log-file", help="訊息另外以 UTF-8 寫進這個檔（排程用：主控台的編碼不可靠）")
    args = parser.parse_args(argv)
    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    from src.megafunds_scraper import MegaFundsScraper

    def say(message: str):
        print(message)
        if args.log_file:
            with open(args.log_file, "a", encoding="utf-8", newline="\n") as f:
                f.write(message + "\n")

    if args.log_file:
        logger.add(args.log_file, level="WARNING", encoding="utf-8")
    result = run(MegaFundsScraper(), pinned_reports.DB_PATH, pinned_reports.DOCS_DIR, pinned_reports.REPORTS_DIR,
                 date.today(), dry_run=args.dry_run, max_days=args.max_days, say=say)
    if args.result_file:
        Path(args.result_file).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
