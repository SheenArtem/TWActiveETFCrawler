"""
日期錯位防護測試

重現 2026-08-05 的錯位情境：投信當日 PCF 未發布時，用請求日期當資料日期的
scraper 會把前一交易日的內容寫成當日。防護應在寫入層擋下。

涵蓋範圍：
1. 防護本體：擋下重複、放行真實變動、不誤擋筆數不同或跨 ETF 的相同內容
2. `source_dated` 豁免：已從來源取得日期的 scraper 不該被擋（誤擋無法補救），
   旗標漏設或群組內不一致時要保守地繼續防護
3. 報表逐檔回退日期 `get_latest_date_on_or_before()`
4. 中信／富邦 `_extract_data_date()`：決定要不要標 source_dated 的解析邏輯

跑法：
    python test_duplicate_guard.py

注意：主測試的斷言都假設防護是開的，因此**強制**把
REJECT_DUPLICATE_OF_PREVIOUS_DAY 設成 True（不是 setdefault——若沿用外部設成
False 的環境，會出現 4 個看起來像真的回歸的假失敗）。最後一項另開子行程把防護
關掉，確認測試對「未修好的實作」是敏感的（red-before）。
Windows 上若終端是 CP950，用 PYTHONIOENCODING=utf-8 執行以免中文輸出出錯。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# config 於 import 時讀取環境變數，因此必須在載入 src 之前設定。
# 用直接指派而非 setdefault：主測試的斷言全都假設防護是開的，
# 沿用外部的 False 會產生假失敗（實測 23/27，4 項假回歸）。
os.environ["REJECT_DUPLICATE_OF_PREVIOUS_DAY"] = "True"

sys.path.insert(0, str(Path(__file__).parent))

from src.database import Database  # noqa: E402

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results = []


def check(name, condition, detail=""):
    results.append((PASS if condition else FAIL, name, detail))
    print(f"  [{PASS if condition else FAIL}] {name}" + (f" — {detail}" if detail else ""))


def rows(etf, date, items):
    """items: [(stock_code, shares, weight)]"""
    return [
        {
            "etf_code": etf, "stock_code": c, "stock_name": f"股票{c}",
            "shares": s, "market_value": 0, "weight": w, "date": date,
        }
        for c, s, w in items
    ]


def rows_sd(etf, date, items, source_dated=True):
    """同 rows()，但每列帶 source_dated（scraper 已從來源取得資料日期）"""
    result = rows(etf, date, items)
    for r in result:
        r["source_dated"] = source_dated
    return result


DAY1 = [("2330", 45999, 6.26), ("2454", 19000, 4.30), ("2383", 14000, 4.21)]
DAY2_CHANGED = [("2330", 46500, 6.30), ("2454", 19000, 4.30), ("2383", 14000, 4.21)]


def fresh_db():
    path = Path(tempfile.mkdtemp()) / "t.db"
    return Database(str(path)), path


def check_source_date_parsers():
    """
    中信／富邦的 _extract_data_date 單元測試。

    這兩個函式決定要不要標 source_dated，而 source_dated 決定寫入層防護是否放行，
    所以解析錯誤會直接變成「錯位資料被放行」或「正確資料被誤擋」。
    純字串／小 Excel 即可測，不需要網路。
    """
    try:
        from src.fubon_scraper import FubonScraper
        from bs4 import BeautifulSoup
    except ImportError as e:
        results.append((SKIP, "富邦 _extract_data_date（缺套件）", str(e)[:60]))
        print(f"  [{SKIP}] 富邦 _extract_data_date — {str(e)[:60]}")
    else:
        soup = BeautifulSoup(
            '<div>基金資產</div><div>資料日期：2026/08/04</div>', 'html.parser'
        )
        check("富邦：頁面有資料日期 -> 取用並標記",
              FubonScraper._extract_data_date(soup, "2026-08-05") == ("2026-08-04", True))
        bare = BeautifulSoup('<div>基金資產</div>', 'html.parser')
        check("富邦：頁面無資料日期 -> 退回請求日且不標記",
              FubonScraper._extract_data_date(bare, "2026-08-05") == ("2026-08-05", False))

    try:
        import pandas as pd
        from src.ctbc_scraper import CTBCScraper
    except ImportError as e:
        results.append((SKIP, "中信 _extract_data_date（缺套件）", str(e)[:60]))
        print(f"  [{SKIP}] 中信 _extract_data_date — {str(e)[:60]}")
        return

    tmp = Path(tempfile.mkdtemp())

    def write_xlsx(name, rows_data):
        path = tmp / name
        pd.DataFrame(rows_data).to_excel(path, index=False, header=False)
        return path

    ok = write_xlsx("ok.xlsx", [["中國信託台灣卓越成長主動式ETF基金", None],
                               ["資料日期", "2026/08/04"],
                               ["股票代碼", "權重"]])
    check("中信：Excel 有資料日期 -> 取用並標記",
          CTBCScraper._extract_data_date(ok, "2026-08-05") == ("2026-08-04", True))

    none = write_xlsx("none.xlsx", [["中國信託", None], ["股票代碼", "權重"]])
    check("中信：Excel 無資料日期 -> 退回請求日且不標記",
          CTBCScraper._extract_data_date(none, "2026-08-05") == ("2026-08-05", False))

    # 民國年目前不支援（正則只吃 20xx）。退回請求日期是安全行為：
    # 不標 source_dated，寫入層防護會繼續攔。若日後中信改用民國年，這個
    # 案例會提醒要擴充正則，而不是靜默錯位。
    roc = write_xlsx("roc.xlsx", [["資料日期", "115/08/04"], ["股票代碼", "權重"]])
    check("中信：民國年 -> 退回請求日且不標記（安全退化）",
          CTBCScraper._extract_data_date(roc, "2026-08-05") == ("2026-08-05", False))

    missing = tmp / "does-not-exist.xlsx"
    check("中信：Excel 讀不到 -> 退回請求日且不標記",
          CTBCScraper._extract_data_date(missing, "2026-08-05") == ("2026-08-05", False))


def check_report_layer():
    """
    報表層：資料日期落後的 ETF 必須同時活在「持股總覽」與「變動追蹤」兩半。

    改用來源日期後，當日 PCF 還沒發布的投信在報表日期那天沒有資料。
    若報表兩半都用單一全域日期去撈，落後的 ETF 會整檔消失。持股總覽靠
    ReportManager 逐檔回退，變動追蹤靠 detect_changes_batch 逐檔回退，缺一不可
    ——只修一半的話這裡的第二個斷言會紅。
    """
    from src.report_manager import ReportManager

    work = Path(tempfile.mkdtemp())
    db = Database(str(work / "t.db"))
    db.insert_etf_list([
        {"etf_code": "00981A", "etf_name": "當日就有資料", "issuer": "EZMoney"},
        {"etf_code": "00995A", "etf_name": "只到前一交易日", "issuer": "CTBC"},
    ])

    # 當日就有資料的投信：8/4 -> 8/5 有變動
    db.insert_holdings(rows_sd("00981A", "2026-08-04", DAY1))
    db.insert_holdings(rows_sd("00981A", "2026-08-05", DAY2_CHANGED))
    # 當日 PCF 還沒發布的投信：最新是 8/4，且 8/3 -> 8/4 確實有變動
    db.insert_holdings(rows_sd("00995A", "2026-08-03", DAY1))
    db.insert_holdings(rows_sd("00995A", "2026-08-04", DAY2_CHANGED))

    report_date = db.get_latest_date()
    mgr = ReportManager(db, work / "reports", work / "docs")
    changes = mgr.analyzer.detect_changes_batch(["00981A", "00995A"], report_date)

    check("報表日期取到 8/5", report_date == "2026-08-05", f"取得 {report_date}")
    check("變動追蹤：當日有資料的 ETF 有被偵測到", "00981A" in changes,
          f"changes={sorted(changes)}")
    check("變動追蹤：落後一天的 ETF 也要被偵測到（逐檔回退）", "00995A" in changes,
          f"changes={sorted(changes)}")

    mgr.generate_all_reports(changes, report_date, append_txt=False)
    data = json.loads(
        (work / "docs" / f"data_{report_date}.json").read_text(encoding="utf-8"))
    overview = {e["etf_code"]: e.get("data_date") for e in data["etf_holdings"]}

    check("持股總覽：落後一天的 ETF 沒有消失", "00995A" in overview,
          f"overview={overview}")
    check("持股總覽：落後的那檔標的是自己的資料日期 8/4",
          overview.get("00995A") == "2026-08-04", f"data_date={overview.get('00995A')}")
    check("持股總覽：當日有資料的那檔標 8/5",
          overview.get("00981A") == "2026-08-05", f"data_date={overview.get('00981A')}")

    # 變動清單也要帶資料日期：來源停更時同一筆變動會在連續多個報表日期重複出現，
    # 沒有這個欄位，首頁個股反查就無法去重，同一次調整會被重複計入買賣張數。
    dc = {e["etf_code"]: e.get("data_date") for e in data["detailed_changes"]}
    check("變動清單每筆都帶 data_date", all(dc.values()), f"detailed_changes={dc}")
    check("變動清單：落後那檔標自己的資料日期 8/4",
          dc.get("00995A") == "2026-08-04", f"data_date={dc.get('00995A')}")

    # 回填腳本必須共用同一個持股總覽出口。它曾經自己組一份（單一日期、無 data_date），
    # 導致回填出來的報表掉了 data_date，且兩半各用一套日期規則。
    regen = (Path(__file__).parent / "scripts" / "regenerate_reports.py").read_text(
        encoding="utf-8")
    check("回填腳本共用 build_etf_holdings", "build_etf_holdings" in regen)
    check("回填腳本沒有自己組一份持股總覽", '"stock_code": h.get' not in regen)


def main():
    print("=== 日期錯位防護（REJECT_DUPLICATE_OF_PREVIOUS_DAY=True）===")
    db, _ = fresh_db()

    # 1. 首日：沒有前一交易日，必須正常寫入
    n = db.insert_holdings(rows("00995A", "2026-08-04", DAY1))
    check("首日資料正常寫入", n == 3, f"寫入 {n} 筆")

    # 2. 核心情境：8/5 抓到與 8/4 完全相同的內容 -> 必須擋下
    n = db.insert_holdings(rows("00995A", "2026-08-05", DAY1))
    stored = db.get_connection().execute(
        "select count(*) from holdings where etf_code='00995A' and date='2026-08-05'"
    ).fetchone()[0]
    check("與前一交易日完全相同 -> 擋下", n == 0 and stored == 0,
          f"回傳 {n}、DB 內 8/5 有 {stored} 筆")

    # 3. 真正有變動的資料必須寫得進去
    n = db.insert_holdings(rows("00995A", "2026-08-05", DAY2_CHANGED))
    stored = db.get_connection().execute(
        "select count(*) from holdings where etf_code='00995A' and date='2026-08-05'"
    ).fetchone()[0]
    check("有實際變動 -> 正常寫入", stored == 3, f"DB 內 8/5 有 {stored} 筆")

    # 4. 只有股數不同也算有變動（不可因權重相同就誤擋）
    db2, _ = fresh_db()
    db2.insert_holdings(rows("00982A", "2026-08-04", [("2330", 1000, 5.0)]))
    db2.insert_holdings(rows("00982A", "2026-08-05", [("2330", 1200, 5.0)]))
    stored = db2.get_connection().execute(
        "select count(*) from holdings where date='2026-08-05'").fetchone()[0]
    check("僅股數不同 -> 視為有變動", stored == 1, f"{stored} 筆")

    # 5. 筆數不同（部分抓取）不應被誤擋
    db3, _ = fresh_db()
    db3.insert_holdings(rows("00984A", "2026-08-04", DAY1))
    db3.insert_holdings(rows("00984A", "2026-08-05", DAY1[:2]))
    stored = db3.get_connection().execute(
        "select count(*) from holdings where date='2026-08-05'").fetchone()[0]
    check("筆數不同 -> 不誤擋", stored == 2, f"{stored} 筆")

    # 6. 不同 ETF 互不影響
    db4, _ = fresh_db()
    db4.insert_holdings(rows("00995A", "2026-08-04", DAY1))
    n = db4.insert_holdings(rows("00406A", "2026-08-05", DAY1))
    check("不同 ETF 相同內容 -> 不擋", n == 3, f"寫入 {n} 筆")

    # 7. 混合批次：只剔除重複的那一檔，其他仍寫入
    db5, _ = fresh_db()
    db5.insert_holdings(rows("00995A", "2026-08-04", DAY1))
    db5.insert_holdings(rows("00982A", "2026-08-04", DAY1))
    mixed = rows("00995A", "2026-08-05", DAY1) + rows("00982A", "2026-08-05", DAY2_CHANGED)
    db5.insert_holdings(mixed)
    conn = db5.get_connection()
    dup = conn.execute(
        "select count(*) from holdings where etf_code='00995A' and date='2026-08-05'").fetchone()[0]
    ok = conn.execute(
        "select count(*) from holdings where etf_code='00982A' and date='2026-08-05'").fetchone()[0]
    check("混合批次只剔除重複的那一檔", dup == 0 and ok == 3,
          f"00995A={dup} 筆 / 00982A={ok} 筆")

    print("=== source_dated 豁免（已從來源取得日期的 scraper 不該被擋）===")

    # 8. source_dated=True：與前一交易日相同也必須寫入。
    #    中信/富邦這類來源的資料日期會往前走，
    #    被誤擋的那天再也抓不回來，所以不能擋。
    db6, _ = fresh_db()
    db6.insert_holdings(rows_sd("00995A", "2026-08-04", DAY1))
    n = db6.insert_holdings(rows_sd("00995A", "2026-08-05", DAY1))
    stored = db6.get_connection().execute(
        "select count(*) from holdings where etf_code='00995A' and date='2026-08-05'"
    ).fetchone()[0]
    check("source_dated=True 且內容相同 -> 不擋", n == 3 and stored == 3,
          f"回傳 {n}、DB 內 8/5 有 {stored} 筆")

    # 9. 解析失敗退回請求日期時 source_dated=False，必須維持防護
    db7, _ = fresh_db()
    db7.insert_holdings(rows_sd("00995A", "2026-08-04", DAY1, source_dated=False))
    n = db7.insert_holdings(rows_sd("00995A", "2026-08-05", DAY1, source_dated=False))
    check("source_dated=False -> 仍然擋下", n == 0, f"回傳 {n}")

    # 10. 混合群組（只有一部分標記）應保守地繼續防護，避免旗標漏設就整批放行
    db8, _ = fresh_db()
    db8.insert_holdings(rows("00995A", "2026-08-04", DAY1))
    mixed = rows_sd("00995A", "2026-08-05", DAY1)
    del mixed[0]['source_dated']          # 其中一列沒有旗標
    n = db8.insert_holdings(mixed)
    check("群組內旗標不一致 -> 保守擋下", n == 0, f"回傳 {n}")

    # 11. source_dated 只是寫入層的判斷依據，不可污染 holdings 表
    cols = [r[1] for r in db6.get_connection().execute("PRAGMA table_info(holdings)")]
    check("source_dated 不會寫進 DB 欄位", 'source_dated' not in cols,
          f"欄位={cols}")

    print("=== 報表逐檔回退日期（get_latest_date_on_or_before）===")

    # 12. 落後一天的 ETF 要能被回退取到，且不可取到晚於上限的資料
    db9, _ = fresh_db()
    db9.insert_holdings(rows_sd("00995A", "2026-08-04", DAY1))       # 中信只到前一日
    db9.insert_holdings(rows("00981A", "2026-08-05", DAY2_CHANGED))  # 統一有當日
    lagging = db9.get_latest_date_on_or_before("00995A", "2026-08-05")
    current = db9.get_latest_date_on_or_before("00981A", "2026-08-05")
    check("落後一天的 ETF 回退到 8/4", lagging == "2026-08-04", f"取得 {lagging}")
    check("有當日資料的 ETF 取到 8/5", current == "2026-08-05", f"取得 {current}")
    check("上限之前無資料 -> None",
          db9.get_latest_date_on_or_before("00995A", "2026-08-03") is None,
          f"取得 {db9.get_latest_date_on_or_before('00995A', '2026-08-03')}")

    print("=== 來源日期解析（scraper）===")
    check_source_date_parsers()

    print("=== 報表層：落後的 ETF 不可從任一半消失 ===")
    check_report_layer()

    # 13. red-before：關閉防護後，重複資料應該會被寫進去
    #    （在子行程執行，因為 config 於 import 時讀取環境變數）
    print("=== 敏感性檢查（關閉防護，預期重複資料會寫入）===")
    script = (
        "import os,sys,tempfile;"
        "sys.path.insert(0, r'" + str(Path(__file__).parent) + "');"
        "from src.database import Database;"
        "from pathlib import Path;"
        "p=Path(tempfile.mkdtemp())/'t.db'; db=Database(str(p));"
        "mk=lambda d: [{'etf_code':'00995A','stock_code':'2330','stock_name':'x',"
        "'shares':1,'market_value':0,'weight':1.0,'date':d}];"
        "db.insert_holdings(mk('2026-08-04'));"
        "db.insert_holdings(mk('2026-08-05'));"
        "print(db.get_connection().execute("
        "\"select count(*) from holdings where date='2026-08-05'\").fetchone()[0])"
    )
    env = dict(os.environ, REJECT_DUPLICATE_OF_PREVIOUS_DAY="False")
    out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                         text=True, env=env, cwd=str(Path(__file__).parent))
    written = (out.stdout.strip().splitlines() or ["?"])[-1]
    check("關閉防護時重複資料會寫入（證明測試有效）", written == "1",
          f"寫入 {written} 筆；stderr={out.stderr.strip()[:120]}")

    failed = [r for r in results if r[0] == FAIL]
    skipped = [r for r in results if r[0] == SKIP]
    passed = len(results) - len(failed) - len(skipped)
    summary = f"=== 結果：{passed}/{len(results) - len(skipped)} 通過"
    print(summary + (f"，{len(skipped)} 項跳過 ===" if skipped else " ==="))
    for _, name, detail in skipped:
        print(f"  SKIPPED: {name} — {detail}")
    if failed:
        for _, name, detail in failed:
            print(f"  FAILED: {name} — {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
