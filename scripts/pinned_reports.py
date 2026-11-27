"""
重生已發布的報表：只有指定的 ETF 用 DB 現在的內容，其他 ETF 固定在發布當時的資料日期。

什麼時候用：事後補進或修正了某幾檔 ETF 的持股（本機回補兆豐、來源停更後回補、歷史日期改標），
要讓那幾天的報表反映出來。不能整份重生：固定落後一天的來源（第一金、00988A）事後 DB 已經補齊，
整份重生會把它們在舊報表裡的資料日期一起往前推，原本那一天的變動就不在任何報表裡了
（見 .ai/guides/date-alignment.md「整串平移」）。

做法：每個報表日期開一個暫存 DB，指定的 ETF 放不晚於報表日期的列，其他 ETF 只放不晚於發布時
data_date 的列，再走現行的產生器。寫回之前逐檔核對：沒指定的 ETF，持股與變動必須與發布版相同。
唯一允許的差別是現行規則本身：自上一份報表以來沒有新資料的 ETF 不重列變動、改列在 stale_etfs
（2026-11-27 以前發布的報表會把同一批變動再列一次；重生時那一批必須與發布版逐項相同才會拿掉）。

內容有變的報表，更新時間改成重生的時間；內容沒變的不寫回。

用法：
    # 兆豐補了 11-25、11-26 的持股之後
    python scripts/pinned_reports.py --etf 00996A --from 2026-11-25

    # 對照：不指定 ETF，全部固定。重生出來的四個檔必須與發布版逐位元組相同，用來確認這台機器
    # 與現行程式重現得出線上的報表（改 DB 之前先跑一次；all＝全部已發布的報表）
    python scripts/pinned_reports.py --control 2026-11-24 2026-11-25
    python scripts/pinned_reports.py --control all

    # 某檔的資料日期不動，但那一天的內容在 DB 裡修過（例如刪掉不該存在的列、改了名稱對照表）
    python scripts/pinned_reports.py --refresh 00994A --from 2026-08-05 --to 2026-10-22

    # 補一份當天沒有產生的報表（每檔取不晚於那一天的最新資料）
    python scripts/pinned_reports.py --create 2026-05-26

    # 只檢查、不寫回
    python scripts/pinned_reports.py --etf 00996A --from 2026-11-25 --dry-run

結束碼：0 全部通過；1 有報表沒通過核對（那一份與它之後的都不會寫回）。
"""
import argparse
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

from src.database import Database  # noqa: E402
from src.report_manager import ReportManager  # noqa: E402

DB_PATH = ROOT / "data" / "etf_holdings.db"
DOCS_DIR = ROOT / "docs"
REPORTS_DIR = ROOT / "reports"

# 07-30 以前發布的報表沒有 market 欄位（前端從代號判斷單位）。比對內容時不看這個欄位。
IGNORED_KEYS = {"market"}
INDEX_SIZE = 90  # 與 ReportManager._update_reports_index 相同


def published_dates(docs_dir: Path = DOCS_DIR) -> List[str]:
    """docs/data_YYYY-MM-DD.json 的所有日期，由舊到新。"""
    return sorted(
        m.group(1) for p in Path(docs_dir).glob("data_*.json")
        if (m := re.fullmatch(r"data_(\d{4}-\d{2}-\d{2})\.json", p.name))
    )


def _strip(value):
    """拿掉比對時不看的欄位（遞迴）。"""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in IGNORED_KEYS}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _by_etf(items: Optional[list]) -> Dict[str, dict]:
    return {e["etf_code"]: e for e in (items or [])}


def _data_dates(payload: dict) -> Dict[str, str]:
    return {e["etf_code"]: e["data_date"] for e in payload.get("etf_holdings", []) if e.get("data_date")}


def _lf(text: str) -> bytes:
    return text.replace("\r\n", "\n").encode("utf-8")


def _build_temp_db(path: Path, source_db: Path, caps: Dict[str, Optional[str]]):
    """暫存 DB：etf_list 全部照抄，每檔 ETF 只放不晚於 caps[etf] 的持股（None＝不放）。來源 DB 以唯讀掛上。"""
    Database(str(path))
    con = sqlite3.connect(str(path), uri=True)
    try:
        con.execute("ATTACH DATABASE ? AS src", (f"file:{quote(Path(source_db).resolve().as_posix())}?mode=ro",))
        con.execute("INSERT INTO etf_list SELECT * FROM src.etf_list")
        for etf_code, cap in caps.items():
            if cap:
                con.execute(
                    "INSERT INTO holdings (id, etf_code, stock_code, stock_name, shares, market_value, weight, date, created_at) "
                    "SELECT id, etf_code, stock_code, stock_name, shares, market_value, weight, date, created_at "
                    "FROM src.holdings WHERE etf_code=? AND date<=? ORDER BY id",
                    (etf_code, cap),
                )
        con.commit()
        con.execute("DETACH DATABASE src")
    finally:
        con.close()


def _source_etfs(source_db: Path) -> List[str]:
    con = sqlite3.connect(f"file:{quote(Path(source_db).resolve().as_posix())}?mode=ro", uri=True)
    try:
        return [row[0] for row in con.execute("SELECT etf_code FROM etf_list ORDER BY etf_code")]
    finally:
        con.close()


def _with_timestamps_of(new_markdown: str, published_markdown: str) -> str:
    """把 Markdown 裡的兩個時間戳換成發布版的值（只用來比對內容是否相同）。"""
    for pattern in (r"^> 最後更新：(.+)$", r"^- 報告生成時間：(.+)$"):
        old = re.search(pattern, published_markdown, flags=re.M)
        new = re.search(pattern, new_markdown, flags=re.M)
        if old and new:
            new_markdown = new_markdown[:new.start(1)] + old.group(1) + new_markdown[new.end(1):]
    return new_markdown


def regenerate(
    report_dates: Iterable[str],
    target_etfs: Iterable[str] = (),
    db_path: Path = DB_PATH,
    docs_dir: Path = DOCS_DIR,
    reports_dir: Path = REPORTS_DIR,
    write: bool = True,
    target_ranges: Optional[Dict[str, tuple]] = None,
    refresh_etfs: Iterable[str] = (),
    create_missing: bool = False,
    keep_going: bool = False,
) -> List[dict]:
    """
    重生 report_dates 這幾份報表（由舊到新處理）。

    Args:
        report_dates: 報表日期（YYYY-MM-DD）。
        target_etfs: 要用 DB 現在內容的 ETF（取不晚於報表日期的最新資料）；其餘固定在發布時的 data_date。
            空集合＝對照模式。
        write: 核對通過時是否寫回 docs/、reports/ 與 reports_index.json。
        target_ranges: 選填，{etf: (起, 迄)}：該檔只在這段報表日期內當成指定的 ETF，其餘日期照樣固定
            （起、迄可為 None）。
        refresh_etfs: 資料日期照樣固定在發布時的值，但那一天的內容在 DB 裡修過（例如刪掉不該存在的列），
            允許與發布版不同。固定落後一天的來源要修內容時用這個，不要放進 target_etfs（那會把
            它的資料日期往前推）。
        create_missing: 沒有發布過的日期是否補產生（每檔取不晚於那一天的最新資料）。預設略過。
        keep_going: 有一份沒通過核對時是否繼續處理後面的日期（盤點用）。預設停下來：後面的報表
            要拿前一份的資料日期判斷哪些 ETF 沒有新資料。

    Returns:
        每份報表一筆：{date, status, problems, notes, changed, identical_bytes, summary}。status 為
        'unchanged'（內容與發布版相同，沒寫回）、'written'、'created'、'verified'（write=False 時
        通過核對、內容會變）、'failed'（沒寫回）、'skipped'。
    """
    docs_dir, reports_dir, db_path = Path(docs_dir), Path(reports_dir), Path(db_path)
    targets = set(target_etfs)
    refresh = set(refresh_etfs)
    target_ranges = target_ranges or {}
    known_dates = set(published_dates(docs_dir))          # 已發布的＋這次補產生的
    new_data_dates: Dict[str, Dict[str, str]] = {}        # 這次處理過的報表 -> 各 ETF 的資料日期
    results = []
    work = Path(tempfile.mkdtemp(prefix="pinned_reports_"))
    failed_at = None
    try:
        for report_date in sorted(set(report_dates)):
            result = {"date": report_date, "status": "skipped", "problems": [], "notes": [], "changed": False,
                      "identical_bytes": None, "summary": None}
            results.append(result)
            if failed_at and not keep_going:
                result["notes"].append(f"{failed_at} 那一份沒通過核對，這一份沒有處理")
                continue
            published_json = docs_dir / f"data_{report_date}.json"
            creating = not published_json.exists()
            if creating and not create_missing:
                result["notes"].append("沒有發布過這一天的報表")
                continue

            published = {} if creating else json.loads(published_json.read_text(encoding="utf-8"))
            pub_holdings = _by_etf(published.get("etf_holdings"))
            pub_changes = _by_etf(published.get("detailed_changes"))
            pub_stale = _by_etf(published.get("stale_etfs"))

            def is_target(etf_code: str) -> bool:
                if creating:
                    return True
                if etf_code not in targets:
                    return False
                first, last = target_ranges.get(etf_code, (None, None))
                return (first is None or first <= report_date) and (last is None or report_date <= last)

            if creating:
                caps = {code: report_date for code in _source_etfs(db_path)}
            else:
                caps = {code: entry.get("data_date") for code, entry in pub_holdings.items()}
                caps.update({code: report_date for code in targets if is_target(code)})

            # 上一份報表各 ETF 的資料日期：這次剛處理過就用新的，否則讀發布版
            earlier = sorted(d for d in known_dates if d < report_date)
            previous_data_dates: Dict[str, str] = {}
            if earlier:
                previous = earlier[-1]
                previous_data_dates = new_data_dates.get(previous) or _data_dates(
                    json.loads((docs_dir / f"data_{previous}.json").read_text(encoding="utf-8")))

            out_root = work / report_date
            out_docs, out_reports = out_root / "docs", out_root / "reports"
            out_docs.mkdir(parents=True)
            out_reports.mkdir(parents=True)
            _build_temp_db(out_root / "temp.db", db_path, caps)
            manager = ReportManager(Database(str(out_root / "temp.db")), out_reports, out_docs)
            etf_names = {e["etf_code"]: e["etf_name"] for e in manager.db.get_active_etfs()}
            changes = manager.analyzer.detect_changes_batch(list(etf_names), report_date)
            if not changes:
                result.update(status="failed", problems=[
                    "這一天沒有任何變動，產生器不會寫出報表；要不要留這份報表得人工決定"])
                failed_at = failed_at or report_date
                shutil.rmtree(out_root, ignore_errors=True)
                continue
            manager.generate_all_reports(changes, report_date, append_txt=False,
                                         previous_data_dates=previous_data_dates)

            new_json = out_docs / f"data_{report_date}.json"
            data = json.loads(new_json.read_text(encoding="utf-8"))
            new_holdings = _by_etf(data.get("etf_holdings"))
            new_changes = _by_etf(data.get("detailed_changes"))
            new_stale = _by_etf(data.get("stale_etfs"))
            # 沒有套「沒有新資料就不重列」時的變動清單：舊規則發布的報表要拿它來對
            unfiltered = _by_etf(manager.html_generator.generate_dashboard_data(
                changes, report_date, etf_names, data.get("etf_holdings"))["detailed_changes"]) if new_stale else {}

            problems, notes = [], []
            for code in sorted(set(pub_holdings) | set(new_holdings) | set(pub_changes) | set(new_changes)
                               | set(pub_stale) | set(new_stale)):
                holdings_same = _strip(pub_holdings.get(code)) == _strip(new_holdings.get(code))
                changes_same = _strip(pub_changes.get(code)) == _strip(new_changes.get(code))
                stale_same = pub_stale.get(code) == new_stale.get(code)
                if holdings_same and changes_same and stale_same:
                    continue
                old_h, new_h = pub_holdings.get(code) or {}, new_holdings.get(code) or {}
                old_c, new_c = pub_changes.get(code) or {}, new_changes.get(code) or {}
                if is_target(code) or code in refresh:
                    notes.append(
                        f"{code}: 資料日期 {old_h.get('data_date')} -> {new_h.get('data_date')}，"
                        f"變動 {old_c.get('total_changes', 0)} -> {new_c.get('total_changes', 0)} 筆，"
                        f"持股 {len(old_h.get('holdings', []))} -> {len(new_h.get('holdings', []))} 檔"
                        + ("，沒有新資料" if code in new_stale else "")
                    )
                elif (holdings_same and code in new_stale and code not in pub_stale and code not in new_changes
                      and _strip(pub_changes.get(code)) == _strip(unfiltered.get(code))):
                    # 舊規則發布的報表：這檔自上一份報表以來沒有新資料，卻把同一批變動再列了一次
                    repeated = old_c.get('total_changes', 0)
                    notes.append(f"{code}: 沒有新資料（資料日期 {new_h.get('data_date')}），"
                                 + (f"不再重列 {repeated} 筆變動" if repeated else "補上標示"))
                else:
                    problems.append(f"{code} 沒有指定卻與發布版不同（持股相同={holdings_same}、"
                                    f"變動相同={changes_same}、沒有新資料的標示相同={stale_same}）")

            new_html = out_docs / f"report_{report_date}.html"
            new_md = out_reports / f"changes_{report_date}.md"
            new_txt = out_reports / f"changes_{report_date}.txt"
            pairs = [(new_json, published_json), (new_html, docs_dir / f"report_{report_date}.html"),
                     (new_md, reports_dir / f"changes_{report_date}.md"),
                     (new_txt, reports_dir / f"changes_{report_date}.txt")]
            fresh = {src: _lf(src.read_text(encoding="utf-8")) for src, _ in pairs}

            if not creating:
                # 逐位元組比對：把時間戳換回發布版的值再比
                kept = dict(data, update_time=published.get("update_time", data["update_time"]))
                published_md = pairs[2][1].read_text(encoding="utf-8") if pairs[2][1].exists() else ""
                comparable = {
                    new_json: _lf(json.dumps(kept, ensure_ascii=False, indent=2)),
                    new_html: _lf(manager.html_generator._generate_report_html(kept)),
                    new_md: _lf(_with_timestamps_of(new_md.read_text(encoding="utf-8"), published_md)),
                    new_txt: fresh[new_txt],
                }
                result["identical_bytes"] = all(
                    dst.exists() and comparable[src] == dst.read_bytes().replace(b"\r\n", b"\n") for src, dst in pairs)
            result.update(problems=problems, notes=notes,
                          summary=(published.get("summary"), data.get("summary")))
            if problems:
                result["status"] = "failed"
                failed_at = failed_at or report_date
                shutil.rmtree(out_root, ignore_errors=True)
                continue

            new_data_dates[report_date] = _data_dates(data)
            content_same = (not creating and not notes
                            and _strip(published.get("summary")) == _strip(data.get("summary")))
            if content_same:
                result["status"] = "unchanged"
            elif not write:
                result.update(status="verified", changed=True)
            else:
                for src, dst in pairs:
                    dst.write_bytes(fresh[src])
                entry = json.loads((out_docs / "reports_index.json").read_text(encoding="utf-8"))[0]
                index_path = docs_dir / "reports_index.json"
                index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else []
                merged = sorted([row for row in index if row["date"] != report_date] + [entry],
                                key=lambda row: row["date"], reverse=True)[:INDEX_SIZE]
                if merged != index:
                    index_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8",
                                          newline="\n")
                result.update(status="created" if creating else "written", changed=True)
            # 補產生的這一份是後面報表的「上一份」；試跑時沒寫檔，資料日期從 new_data_dates 拿
            known_dates.add(report_date)
            shutil.rmtree(out_root, ignore_errors=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return results


def print_results(results: List[dict]) -> bool:
    """印出每份報表的結果；全部通過回 True。"""
    ok = True
    for r in results:
        line = f"{r['date']}: {r['status']}"
        if r.get("summary"):
            line += f"  摘要 {r['summary'][0]} -> {r['summary'][1]}"
        if r["status"] == "unchanged":
            line += f"  四個檔逐位元組相同={r['identical_bytes']}"
        print(line)
        for note in r.get("notes", []):
            print(f"    {note}")
        for problem in r.get("problems", []):
            print(f"    !! {problem}")
        if r["status"] == "failed":
            ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="重生已發布的報表：只有指定的 ETF 用 DB 現在的內容，其他固定在發布當時的資料日期")
    parser.add_argument("--etf", action="append", default=[], help="要用 DB 現在內容的 ETF 代號（可重複）")
    parser.add_argument("--refresh", action="append", default=[],
                        help="資料日期不動、但內容在 DB 裡修過的 ETF 代號（可重複）")
    parser.add_argument("--from", dest="first", help="第一個報表日期（含）")
    parser.add_argument("--to", dest="last", help="最後一個報表日期（含），預設到最新一份")
    parser.add_argument("--control", nargs="+", metavar="DATE",
                        help="對照模式：這幾份報表（或 all）全部固定在發布時的資料日期，重生結果必須與發布版逐位元組相同")
    parser.add_argument("--create", nargs="+", metavar="DATE", help="補產生當天沒有發布的報表")
    parser.add_argument("--db", default=str(DB_PATH), help="來源 DB（預設 data/etf_holdings.db）")
    parser.add_argument("--dry-run", action="store_true", help="只核對、不寫回")
    args = parser.parse_args()
    logger.remove()

    if args.control:
        dates = published_dates() if args.control == ["all"] else args.control
        results = regenerate(dates, db_path=Path(args.db), write=False, keep_going=True)
        print_results(results)
        mismatched = [r["date"] for r in results if r["status"] != "unchanged" or not r["identical_bytes"]]
        if mismatched:
            print(f"對照沒過：{mismatched}（重生結果與發布版不同）")
            return 1
        print(f"對照通過：{len(results)} 份報表重生後與發布版逐位元組相同")
        return 0

    if args.create:
        existing = [d for d in args.create if d in published_dates()]
        if existing:
            parser.error(f"這幾天已經有報表：{existing}（--create 只補沒有發布過的日期）")
        results = regenerate(args.create, db_path=Path(args.db), write=not args.dry_run, create_missing=True)
        return 0 if print_results(results) else 1

    if not (args.etf or args.refresh) or not args.first:
        parser.error("要給 --etf 或 --refresh，以及 --from（或用 --control、--create）")
    dates = [d for d in published_dates() if d >= args.first and (not args.last or d <= args.last)]
    results = regenerate(dates, args.etf, db_path=Path(args.db), write=not args.dry_run,
                         refresh_etfs=args.refresh)
    return 0 if print_results(results) else 1


if __name__ == "__main__":
    sys.exit(main())
