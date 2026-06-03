"""
一次性 backfill：以統一後的台股名稱重新產生所有已發布日期的報告。

成分股名稱正規化（src/stock_names.py）作用於 Database.get_holdings_by_date()，
因此只要從 DB 重新產生報告，docs 的 JSON/HTML 與 reports 的 MD/TXT 名稱即會統一。

重新產生對象：docs/data_*.json 所對應的每一個日期（含無變動日）。
保留各報告原本的 update_time，使 diff 僅反映名稱變化。

執行：
    python scripts/regenerate_reports.py
"""
import json
import re
import sys
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.database import Database  # noqa: E402
from src.report_manager import ReportManager  # noqa: E402

DB_PATH = ROOT / "data" / "etf_holdings.db"
DOCS_DIR = ROOT / "docs"
REPORTS_DIR = ROOT / "reports"


def published_dates() -> list:
    """從 docs/data_YYYY-MM-DD.json 取得所有已發布日期（由舊到新）。"""
    dates = []
    for p in DOCS_DIR.glob("data_*.json"):
        m = re.match(r"data_(\d{4}-\d{2}-\d{2})\.json$", p.name)
        if m:
            dates.append(m.group(1))
    return sorted(dates)


def main():
    db = Database(str(DB_PATH))
    mgr = ReportManager(db, REPORTS_DIR, DOCS_DIR)

    etf_info = db.get_active_etfs()
    etf_info_dict = {e["etf_code"]: e["etf_name"] for e in etf_info}
    etf_codes = list(etf_info_dict.keys())

    dates = published_dates()
    logger.info(f"Regenerating {len(dates)} dates with normalized names")

    for date in dates:
        # 建立持股資料（經 get_holdings_by_date 正規化名稱）
        etf_holdings = []
        for code in etf_codes:
            holdings = db.get_holdings_by_date(date, code)
            if holdings:
                etf_holdings.append({
                    "etf_code": code,
                    "etf_name": etf_info_dict.get(code, code),
                    "holdings": [
                        {
                            "stock_code": h.get("stock_code", ""),
                            "stock_name": h.get("stock_name", ""),
                            "weight": h.get("weight", 0),
                            "lots": h.get("shares", 0) / 1000 if h.get("shares") else 0,
                        }
                        for h in holdings
                    ],
                })

        if not etf_holdings:
            logger.warning(f"{date}: no holdings in DB, skipped")
            continue

        changes_dict = db_changes(mgr, etf_codes, date)

        # 保留原本的 update_time
        old_update_time = None
        json_path = DOCS_DIR / f"data_{date}.json"
        if json_path.exists():
            try:
                old_update_time = json.loads(json_path.read_text(encoding="utf-8")).get("update_time")
            except (OSError, json.JSONDecodeError):
                pass

        # 重生 JSON + HTML（無變動日也照常重寫）
        mgr.html_generator.generate_daily_report(changes_dict, date, etf_info_dict, etf_holdings)

        if old_update_time:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            data["update_time"] = old_update_time
            json_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        # 有變動的日期才重生 MD/TXT changelog
        if changes_dict:
            md = mgr.analyzer.generate_markdown_report(changes_dict, date)
            (REPORTS_DIR / f"changes_{date}.md").write_text(md, encoding="utf-8")
            txt = mgr.analyzer.generate_report(changes_dict, date)
            (REPORTS_DIR / f"changes_{date}.txt").write_text(txt, encoding="utf-8")

        logger.info(f"{date}: regenerated ({len(changes_dict)} ETFs changed)")

    logger.info("Backfill complete")


def db_changes(mgr, etf_codes, date):
    """偵測指定日期的變動（名稱已於 DB 讀取時正規化）。"""
    return mgr.analyzer.detect_changes_batch(etf_codes, date)


if __name__ == "__main__":
    main()
