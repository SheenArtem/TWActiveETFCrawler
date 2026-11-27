"""Index the two source dates for published reports that predate schema version 2."""
from contextlib import closing
from datetime import date, timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import mkstemp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.trading_calendar import last_trading_day


def build_baselines(reports_dir, database):
    previous = {}
    last = {}
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        for code, source_date in connection.execute(
            "SELECT DISTINCT etf_code, date FROM holdings ORDER BY etf_code, date"
        ):
            previous[code, source_date] = last.get(code)
            last[code] = source_date

    result = {}
    prior_report = None
    for path in sorted(reports_dir.glob("data_????-??-??.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        day = report["date"]
        if report.get("report_schema_version", 1) < 2:
            funds = {}
            for fund in report.get("etf_holdings", []):
                code, source = fund["etf_code"], fund.get("data_date")
                if (code, source) in previous:
                    funds[code] = [source, previous[code, source]]
            result[day] = {
                "updateTime": report.get("update_time"),
                "previousTradingDate": last_trading_day(date.fromisoformat(day) - timedelta(days=1)).isoformat(),
                "previousReportDate": prior_report,
                "funds": funds,
            }
        prior_report = day
    return result


if __name__ == "__main__":
    docs = ROOT / "docs"
    payload = build_baselines(docs, ROOT / "data" / "etf_holdings.db")
    destination = docs / "assets" / "report-baselines.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    # One line per date keeps the archive compact and corrections reviewable.
    entries = [json.dumps(day) + ":" + json.dumps(row, separators=(",", ":")) for day, row in payload.items()]
    descriptor, name = mkstemp(dir=destination.parent, prefix=".report-baselines-", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as out:
            out.write("{\n" + ",\n".join(entries) + "\n}\n")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
