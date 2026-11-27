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
5. 海外成分股（00988A 主動統一全球創新）：Bloomberg 代號要連市場後綴一起收與存、
   名稱正規化不可碰海外代號、報表單位台股「張」／海外「千股」
6. 統一 00981A：Excel 股票表位置會隨版面移動（期貨段在前）、API 備援要以 TranDate
   （持股基準日）而非請求日期當資料日期
7. 國定假日：請求日期與報表日期要比照週末退回最近一個交易日（2026-09-25 中秋的假報表）
8. 首頁跨報表去重、資料涵蓋與持股日期由同一個 CI 的 tests/market-data.test.mjs 驗證。
9. 摩根 PCF `NAV Date`、野村 API `NavDate`、復華 Excel 表頭 `日期:` 的來源日期解析與非 xlsx 防呆
10. 2026-11 靜默停更的來源：聯博 xlsx 改版（表頭「權重(%)」、代碼欄改台股代號）、
    第一金 API 尾端的彙總列不是持股、中信持股頁的網域
11. 來源停更警報（scripts/check_stale_sources.py）：落後交易日數的算法與班次是否失敗
12. 沒有新資料的 ETF 在報表列入 stale_etfs，保留持股日期及落後交易日數。
13. 只重生指定 ETF 的歷史報表（scripts/pinned_reports.py）：其他 ETF 固定在發布當時的資料日期
14. 本機回補兆豐（scripts/backfill_megafunds.py）：歷史查詢的日期換算、只補缺的交易日、補完重生報表

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
import shutil
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


def check_batch2_parsers():
    """
    第二批轉換的日期解析：台新／安聯／群益／摩根。

    這些函式決定要不要標 source_dated，而 source_dated 決定寫入層防護是否放行，
    解析錯誤會直接變成「錯位資料被放行」或「正確資料被誤擋」。全部可離線測。
    """
    from bs4 import BeautifulSoup

    print("--- 台新：日期黏在「每基數」表頭前 ---")
    from src.tsit_scraper import TSITScraper
    ok = BeautifulSoup(
        '<p class="small">日期：<input id="PUB_DATE" value="2026-08-06" /></p>'
        '<table><tr><th>2026/8/5每基數實際申購總價金(元)</th><td>TWD 1</td></tr>'
        '<tr><th>2026/8/5每基數申購總價金差額(元)</th><td>TWD 2</td></tr></table>',
        'html.parser')
    check("台新：取「每基數」前的日期且不受 #PUB_DATE 干擾",
          TSITScraper._extract_data_date(ok, "2026-08-06") == ("2026-08-05", True))
    bare = BeautifulSoup('<p>日期：<input id="PUB_DATE" value="2026-08-06" /></p>', 'html.parser')
    check("台新：找不到錨點 -> 退回請求日且不標記",
          TSITScraper._extract_data_date(bare, "2026-08-06") == ("2026-08-06", False))
    conflict = BeautifulSoup(
        '<th>2026/8/5每基數實際申購總價金</th><th>2026/8/4每基數申購總價金差額</th>',
        'html.parser')
    check("台新：頁面出現兩個不同日期 -> 視為改版，保守退回",
          TSITScraper._extract_data_date(conflict, "2026-08-06") == ("2026-08-06", False))

    print("--- 安聯：頁面「資料日期 :」標籤 ---")
    from src.allianz_scraper import AllianzScraper
    check("安聯：有資料日期 -> 取用並標記",
          AllianzScraper._extract_data_date(
              "持股比重 配息紀錄 資料日期 : 2026/08/05 基金資產", "2026-08-06"
          ) == ("2026-08-05", True))
    check("安聯：無資料日期 -> 退回請求日且不標記",
          AllianzScraper._extract_data_date("基金資產 淨值", "2026-08-06")
          == ("2026-08-06", False))

    print("--- 群益：buyback API 的 pcf.date2 ---")
    from src.capital_scraper import CapitalScraper
    payload = {"data": {"pcf": {"date1": "2026-08-06", "date2": "2026-08-05"},
                        "stocks": [
                            {"stocNo": "2330", "stocName": "台積電", "share": 1794000.0,
                             "weight": 8.522, "date1": "2026/8/6 上午 12:00:00"},
                            {"stocNo": "ABC", "stocName": "非股票列", "share": 1, "weight": 1},
                        ]}}
    rows_out, d, sd = CapitalScraper._parse_api_response(payload, "00982A", "2026-08-06")
    check("群益：用 pcf.date2 而非 date1，且過濾非 4 碼代號",
          d == "2026-08-05" and sd is True and len(rows_out) == 1
          and rows_out[0]["shares"] == 1794000 and rows_out[0]["source_dated"] is True)
    no_date = {"data": {"pcf": {"date1": "2026-08-06"},
                        "stocks": [{"stocNo": "2330", "stocName": "台積電",
                                    "share": 1, "weight": 1}]}}
    rows_out, d, sd = CapitalScraper._parse_api_response(no_date, "00982A", "2026-08-06")
    check("群益：date2 缺漏 -> 退回請求日且不標記",
          d == "2026-08-06" and sd is False and rows_out[0]["source_dated"] is False)
    rows_out, d, sd = CapitalScraper._parse_api_response({}, "00982A", "2026-08-06")
    check("群益：整包壞掉 -> 空列表＋退回請求日", rows_out == [] and sd is False)

    print("--- 摩根：優先讀 PCF 表頭 NAV Date；缺漏時才退回 Valuation Date 領先判準 ---")
    import io
    import openpyxl
    from src.morgan_scraper import MorganScraper
    vd = MorganScraper._parse_valuation_date("20260806")
    check("摩根：日期解析支援 YYYYMMDD／float／非法字串",
          vd == "2026-08-06"
          and MorganScraper._parse_valuation_date(20261022.0) == "2026-10-22"
          and MorganScraper._parse_valuation_date("bad-date") == ""
          and MorganScraper._parse_valuation_date(None) == "")
    check("摩根：有 NAV Date -> 直接採用實際持股日並標記（不受 Valuation Date 或颱風假請求日影響）",
          MorganScraper._extract_data_date(
              {"Valuation Date": "20261027", "NAV Date": "20261022"}, "2026-10-23", "00401A"
          ) == ("2026-10-22", True))
    check("摩根：NAV Date 缺漏且 VD 領先請求日 -> 夾回請求日並標記（備援）",
          MorganScraper._extract_data_date(
              {"Valuation Date": "20260806"}, "2026-08-05", "00401A"
          ) == ("2026-08-05", True))
    check("摩根：NAV Date 缺漏且 VD 未領先 -> 舊檔不標記（備援）",
          MorganScraper._extract_data_date(
              {"Valuation Date": "20260806"}, "2026-08-06", "00401A"
          ) == ("2026-08-06", False))
    check("摩根：兩者皆缺漏 -> 退回請求日且不標記",
          MorganScraper._extract_data_date({}, "2026-08-06", "00401A") == ("2026-08-06", False))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Record Type", "Valuation Date", "NAV Date", "Estimated Total Market Value"])
    ws.append(["H", "20261027", "20261022", 1000000])
    ws.append(["Record Type", "Constituent Ticker", "Constituent Description",
               "Shares or PAR Amount", "Market Value Base"])
    ws.append(["D", "2330", "TAIWAN SEMICONDUCTOR", 1000, 250000])
    buf = io.BytesIO()
    wb.save(buf)
    m_scraper = MorganScraper()
    m_scraper._download_pcf = lambda etf_code, isin: buf.getvalue()
    m_rows = m_scraper.get_etf_holdings("00401A", "2026-10-23")
    check("摩根：get_etf_holdings 在臨時休市日請求 10-23 時，依 NAV Date 寫 10-22 而非假日期",
          len(m_rows) == 1 and m_rows[0]["date"] == "2026-10-22"
          and m_rows[0]["source_dated"] is True and m_rows[0]["weight"] == 25.0,
          f"rows={m_rows}")


def check_batch3_parsers():
    """
    第三批新增來源的日期解析與表格定位：兆豐／凱基／永豐（2026-08-09 新增）。

    三家頁面最顯眼的日期都是 PCF 適用日（下一營業日），資料日期在別的地方；
    抓錯就直接錯位，而且三家都標 source_dated（寫入層防護會放行），
    所以解析錯誤不會被防護攔住。全部可離線測。
    """
    from bs4 import BeautifulSoup

    print("--- 兆豐：日期黏在「每基數」金額欄位前，「查詢日期」是適用日 ---")
    from src.megafunds_scraper import MegaFundsScraper
    ok = BeautifulSoup(
        '<p>申購買回清單 查詢日期 2026/08/10 現金申購買回清單公告</p>'
        '<p>每申購基數之預收申購總價金(元) TWD$ 7,320,000 '
        '2026/08/07 每基數申購總價金差異額(元) TWD$ -795,999 '
        '2026/08/07 每基數實際申購總價金(元) TWD$ 6,654,001</p>',
        'html.parser')
    check("兆豐：取「每基數」前的日期，不受「查詢日期」干擾",
          MegaFundsScraper._extract_data_date(ok, "2026-08-10") == ("2026-08-07", True))
    bare = BeautifulSoup('<p>申購買回清單 查詢日期 2026/08/10</p>', 'html.parser')
    check("兆豐：找不到錨點 -> 退回請求日且不標記",
          MegaFundsScraper._extract_data_date(bare, "2026-08-10") == ("2026-08-10", False))
    conflict = BeautifulSoup(
        '<p>2026/08/07 每基數實際申購總價金 2026/08/06 每基數申購總價金差異額</p>',
        'html.parser')
    check("兆豐：頁面出現兩個不同日期 -> 視為改版，保守退回",
          MegaFundsScraper._extract_data_date(conflict, "2026-08-10") == ("2026-08-10", False))

    stock_table = (
        '<table class="table-stock">'
        '<tr><td>股票代號</td><td>股票名稱</td><td>股數</td><td>持股權重</td></tr>'
        '<tr><td>2330</td><td>台積電</td><td>179,000</td><td>9.95%</td></tr></table>'
        '<table class="table-futures">'
        '<tr><td>期貨代號</td><td>期貨名稱</td><td>契約年月</td><td>口數</td><td>持股權重</td></tr>'
        '<tr><td>MTX</td><td>小型臺指期貨</td><td>2026/08</td><td>38</td><td>1.35%</td></tr></table>'
    )
    mega_rows = MegaFundsScraper()._parse_html_table(
        BeautifulSoup(stock_table, 'html.parser'), "2026-08-07", "00996A", True)
    check("兆豐：只取股票表，期貨表不混進來",
          len(mega_rows) == 1 and mega_rows[0]["stock_code"] == "2330"
          and mega_rows[0]["shares"] == 179000 and mega_rows[0]["source_dated"] is True,
          f"取得 {len(mega_rows)} 列")

    print("--- 凱基：括號內的淨值基準日，#DataDate 是適用日 ---")
    from src.kgi_scraper import KGIScraper
    kgi_ok = BeautifulSoup(
        '<input id="DataDate" name="DataDate" value="2026/08/10" />'
        '<p>主動凱基台灣(00407A) 2026/08/10 現金申購買回清單公告 '
        '基金淨資產價值(元) TWD$28,702,559,786 '
        '(2026/08/07)每受益權單位淨資產價值(元) TWD$9.31</p>',
        'html.parser')
    check("凱基：取括號內基準日，不受 #DataDate 干擾",
          KGIScraper._extract_data_date(kgi_ok, "2026-08-10") == ("2026-08-07", True))
    kgi_bare = BeautifulSoup(
        '<input id="DataDate" value="2026/08/10" /><p>現金申購買回清單公告</p>', 'html.parser')
    check("凱基：找不到錨點 -> 退回請求日且不標記",
          KGIScraper._extract_data_date(kgi_bare, "2026-08-10") == ("2026-08-10", False))

    kgi_rows = KGIScraper()._parse_html_table(
        BeautifulSoup(
            '<table class="responsive-table">'
            '<tr><th>股票代號</th><th>股票名稱</th><th>股數</th><th>權重(%)</th></tr>'
            '<tr><td>2330</td><td>台積電</td><td>991,000</td><td>8.18</td></tr>'
            '<tr><td>合計</td><td></td><td></td><td>96.25</td></tr></table>',
            'html.parser'),
        "2026-08-07", "00407A", True)
    check("凱基：解析持股列並排除合計列",
          len(kgi_rows) == 1 and kgi_rows[0]["shares"] == 991000
          and kgi_rows[0]["weight"] == 8.18,
          f"取得 {len(kgi_rows)} 列")

    print("--- 永豐：頁面「資料日期：」，qdate 是適用日 ---")
    from src.sinopac_scraper import SinoPacScraper
    # fixture 照抄真實頁面的排列：適用日 08/10 緊貼在「每申購基數」前面
    # （與兆豐／台新相反！那兩家「每基數」前面才是基準日）。
    # 這樣若有人把永豐改成「每基數」錨或泛抓日期，這個 check 會變紅。
    spf_ok = BeautifulSoup(
        '<input id="qdate" value="2026-08-10" /><input id="hDate" name="hDate" value="2026-08-10" />'
        '<p>永豐台灣科技趨勢主動式ETF（證劵代碼：00410A）2026/08/10 '
        '每申購基數之預收申購總價金(元) NT$ 5,847,000 '
        '2026/08/07 基金淨資產價值(元) NT$ 1,729,928,119 資料日期：2026/08/07</p>',
        'html.parser')
    check("永豐：取「資料日期」，不受 qdate／hDate／「每基數」前的適用日干擾",
          SinoPacScraper._extract_data_date(spf_ok, "2026-08-10") == ("2026-08-07", True))
    spf_bare = BeautifulSoup('<input id="qdate" value="2026-08-10" /><p>基金資產</p>', 'html.parser')
    check("永豐：找不到資料日期 -> 退回請求日且不標記",
          SinoPacScraper._extract_data_date(spf_bare, "2026-08-10") == ("2026-08-10", False))
    spf_conflict = BeautifulSoup(
        '<p>資料日期：2026/08/07 ... 資料日期：2026/08/06</p>', 'html.parser')
    check("永豐：桌機／手機版標了兩個不同日期 -> 視為改版，保守退回",
          SinoPacScraper._extract_data_date(spf_conflict, "2026-08-10") == ("2026-08-10", False))

    # 桌機版一大表 + 手機版每檔一小表：盲抓會重複計算，只能取桌機版
    spf_rows = SinoPacScraper()._parse_html_table(
        BeautifulSoup(
            '<table class="tab_sh tab_sh-w">'
            '<tr><th>證券代碼</th><th>證券名稱</th><th>股數</th><th>佔基金淨資產之權重(%)</th></tr>'
            '<tr><td>2330</td><td>台積電</td><td>50,000</td><td>6.86</td></tr></table>'
            '<table class="tab_sh tab_sh-m">'
            '<tr><th>證券代碼</th><td>2330</td></tr>'
            '<tr><th>證券名稱</th><td>台積電</td></tr>'
            '<tr><th>股數</th><td>50,000</td></tr>'
            '<tr><th>佔基金淨資產之權重(%)</th><td>6.86</td></tr></table>',
            'html.parser'),
        "2026-08-07", "00410A", True)
    check("永豐：手機版重複表格不會被重複計算",
          len(spf_rows) == 1 and spf_rows[0]["stock_code"] == "2330"
          and spf_rows[0]["shares"] == 50000,
          f"取得 {len(spf_rows)} 列")


def check_batch4_parsers():
    """
    第四批轉換（2026-10-27）：野村 API `NavDate` 與復華投資組合 Excel 表頭 `日期:`。

    兩者結構上雖嚴格遵守請求日期，但補齊來源日期解析與 `source_dated=True` 後，
    22/23 檔皆由來源本身決定資料日期（僅餘國泰 00400A 無日期欄位），且復華對非交易日
    或未發布日的 `'查無資料'` 純文字回應不再寫入損毀 `.xlsx`。全部離線可測。
    """
    import pandas as pd
    import src.fhtrust_scraper as fh_mod
    from src.fhtrust_scraper import FHTrustScraper
    from src.nomura_scraper import NomuraScraper

    print("--- 野村：GetFundAssets 的 FundAsset.NavDate 與股票表 NavDate ---")
    check("野村：兩處 NavDate 一致 -> 取用並標記",
          NomuraScraper._extract_data_date(
              {"FundAsset": {"NavDate": "2026/10/22"}},
              {"TableTitle": "股票", "NavDate": "2026/10/22"},
              "2026-10-23",
          ) == ("2026-10-22", True))
    check("野村：單數月日（2026/8/5）正規化為 YYYY-MM-DD",
          NomuraScraper._extract_data_date(
              {"FundAsset": {"NavDate": "2026/8/5"}}, None, "2026-08-06"
          ) == ("2026-08-05", True))
    check("野村：FundAsset 與股票表 NavDate 不一致 -> 保守退回且不標記",
          NomuraScraper._extract_data_date(
              {"FundAsset": {"NavDate": "2026/10/22"}},
              {"TableTitle": "股票", "NavDate": "2026/10/21"},
              "2026-10-23",
          ) == ("2026-10-23", False))
    check("野村：無 NavDate -> 退回請求日且不標記",
          NomuraScraper._extract_data_date(
              {"FundAsset": None}, {"TableTitle": "股票"}, "2026-10-23"
          ) == ("2026-10-23", False))

    ns = NomuraScraper()
    ns.get_fund_assets = lambda fund_id, d: {
        "Entries": {
            "Data": {
                "FundAsset": {"NavDate": "2026/10/22"},
                "Table": [
                    {"TableTitle": "期貨", "NavDate": "2026/10/22",
                     "Rows": [["TX", "台指期", "10", "1.5%"]]},
                    {"TableTitle": "股票", "NavDate": "2026/10/22",
                     "Rows": [["2330", "台積電", "1,234,000", "9.85%"]]},
                ],
            }
        }
    }
    n_rows = ns.get_etf_holdings("00980A", "2026-10-27")
    check("野村：get_etf_holdings 只收股票表、採用 NavDate 並標記 source_dated",
          len(n_rows) == 1 and n_rows[0]["stock_code"] == "2330"
          and n_rows[0]["shares"] == 1234000 and n_rows[0]["weight"] == 9.85
          and n_rows[0]["date"] == "2026-10-22" and n_rows[0]["source_dated"] is True,
          f"rows={n_rows}")

    ns.get_fund_assets = lambda fund_id, d: {"Entries": {"Data": {"FundAsset": None, "Table": []}}}
    check("野村：非交易日／未發布（Table 為空）-> 空列表",
          ns.get_etf_holdings("00980A", "2026-10-23") == [])

    print("--- 復華：Excel 表頭「日期: YYYY/MM/DD」、動態表頭定位與非 xlsx 防呆 ---")
    tmp = Path(tempfile.mkdtemp())

    def write_fh_xlsx(name, rows_data):
        p = tmp / name
        pd.DataFrame(rows_data).to_excel(p, index=False, header=False)
        return p

    fh_layout = [
        ["復華台灣未來50主動式ETF基金（證劵代碼：00991A）", None, None, None, None],
        [None] * 5,
        ["日期: 2026/10/22", None, None, None, None],
        ["基金資產淨值", None, None, None, None],
        ["68,178,935,634", None, None, None, None],
        ["基金在外流通單位數", None, None, None, None],
        ["4,108,416,000", None, None, None, None],
        ["基金每單位淨值", None, None, None, None],
        [16.59, None, None, None, None],
        [None] * 5,
        ["證券代號", "證券名稱", "股數", "金額", "權重(%)"],
        ["2330", "台灣積體", "4,200,000", "10,017,000,000", "14.692%"],
        ["合計", None, None, None, "98.500%"],
    ]
    fh_ok = write_fh_xlsx("fh_ok.xlsx", fh_layout)
    fh = FHTrustScraper()
    fh.download_dir = tmp
    fh_rows = fh.parse_excel_file(fh_ok, "00991A", "2026-10-23")
    check("復華：取表頭「日期: 2026/10/22」並標記 source_dated，排除合計列",
          len(fh_rows) == 1 and fh_rows[0]["stock_code"] == "2330"
          and fh_rows[0]["shares"] == 4200000 and fh_rows[0]["weight"] == 14.692
          and fh_rows[0]["date"] == "2026-10-22" and fh_rows[0]["source_dated"] is True,
          f"rows={fh_rows}")

    # 若上方插入期貨段使「證券代號」移到第 14 列，仍應定位到股票表且不混入期貨代號
    fh_shifted = write_fh_xlsx(
        "fh_shifted.xlsx",
        fh_layout[:10]
        + [["期貨代號", "期貨名稱", "口數", "金額", "權重(%)"],
           ["TX", "台指期", "20", "0", "1.2%"],
           [None] * 5]
        + fh_layout[10:],
    )
    shifted_rows = fh.parse_excel_file(fh_shifted, "00991A", "2026-10-23")
    check("復華：表頭下移且含期貨列時仍正確取回股票列",
          [r["stock_code"] for r in shifted_rows] == ["2330"]
          and shifted_rows[0]["date"] == "2026-10-22")

    fh_no_date = write_fh_xlsx("fh_nodate.xlsx", [fh_layout[0]] + fh_layout[10:])
    nd_rows = fh.parse_excel_file(fh_no_date, "00991A", "2026-10-23")
    check("復華：表頭無日期 -> 退回請求日且不標記 source_dated",
          len(nd_rows) == 1 and nd_rows[0]["date"] == "2026-10-23"
          and nd_rows[0]["source_dated"] is False)

    fh_conflict = write_fh_xlsx(
        "fh_conflict.xlsx",
        [["日期: 2026/10/22"], ["日期: 2026/10/21"], ["證券代號", "證券名稱", "股數", "金額", "權重(%)"]],
    )
    check("復華：表頭出現兩個不同日期 -> 保守退回且不標記",
          FHTrustScraper._extract_data_date(fh_conflict, "2026-10-23") == ("2026-10-23", False))

    class FakeTextResponse:
        status_code = 200
        content = "查無資料".encode("utf-8")

        def raise_for_status(self):
            pass

    orig_get = fh_mod.requests.get
    try:
        fh_mod.requests.get = lambda url, timeout=30: FakeTextResponse()
        dl = fh.download_portfolio_excel("ETF23", "2026-10-23")
    finally:
        fh_mod.requests.get = orig_get
    check("復華：未發布日回純文字「查無資料」時回傳 None 且不存壞檔",
          dl is None and not (tmp / "ETF23_20261023.xlsx").exists())


def check_stalled_source_fixes():
    """
    2026-11 三個靜默停更／寫錯的來源（來源改版後 scraper 每班失敗或多寫，workflow 卻一直是綠的）：

    1. 聯博 00404A：xlsx 股票表頭的權重欄從「權重」改成「權重(%)」、代碼欄從 ISIN 改成台股代號，
       表頭要求完全相等的舊寫法從 11-11 起找不到股票表。
    2. 第一金 00408A／00994A：API 回應尾端三列彙總（現金/存款、股票、其他+負債）被當成持股寫入。
    3. 中信 00995A／00406A：舊網域 .com 的頁面跨網域呼叫 .com.tw 的 API 被擋，11-04 起沒有下載按鈕。
       這個失敗條件要真的連網才重現（2026-11-27 runner 診斷 run 45921910996），這裡只釘住網域。
    """
    import io

    try:
        import openpyxl
        from src.abfunds_scraper import ABFundsScraper
    except ImportError as e:
        results.append((SKIP, "聯博 xlsx 版面（缺套件）", str(e)[:60]))
        print(f"  [{SKIP}] 聯博 xlsx 版面 — {str(e)[:60]}")
    else:
        def xlsx_bytes(rows_data):
            wb = openpyxl.Workbook()
            ws = wb.active
            for row in rows_data:
                ws.append(row)
            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue()

        class FakeXlsResponse:
            def __init__(self, content):
                self.content = content
                self.headers = {"content-disposition": "attachment; filename=2026-11-26-Portfolio-Holding.xlsx"}

        def ab_parse(rows_data):
            scraper = ABFundsScraper()
            scraper._download_xls = lambda etf_code, share_class_id: FakeXlsResponse(xlsx_bytes(rows_data))
            return scraper.get_etf_holdings("00404A", "2026-11-27")

        # 2026-11-26 實際檔案的結構（節錄）：上方的基金資產摘要也有「權重(%)」欄，不可誤認成股票表
        new_layout = [
            ["TW00000404A5 聯博台灣動能收益50主動式ETF"],
            ["2026/11/26 基金持股權重"],
            [None],
            ["基金資產"],
            ["項目", "市值/名目本金", "權重(%)"],
            ["股票", "3,009,847,371.00", "88.76%"],
            [None],
            ["股票"],
            ["代碼", "名稱", "股數", "市值", "權重(%)"],
            ["2330", "台灣積體電路製造", "356,000", "763,620,000.00", "22.52%"],
            ["2637", "慧洋海運股份有限公司", "403,000", "36,068,500.00", "1.06%"],
            [None],
            ["期貨"],
            ["代碼", "名稱", "口數", "市值", "權重(%)"],
            [None, "台股期貨12/26", "83", "655,567,200.00", "19.33%"],
        ]
        got = ab_parse(new_layout)
        check("聯博：表頭「權重(%)」＋台股代號（2026-11 改版後）-> 解析出股票表",
              [(h["stock_code"], h["shares"], h["market_value"], h["weight"]) for h in got]
              == [("2330", 356000, 763620000.0, 22.52), ("2637", 403000, 36068500.0, 1.06)],
              f"{[(h['stock_code'], h['shares'], h['market_value'], h['weight']) for h in got]}")
        check("聯博：資料日期取自檔名並標 source_dated；期貨表（口數）不收",
              bool(got) and {h["date"] for h in got} == {"2026-11-26"}
              and all(h["source_dated"] is True for h in got) and len(got) == 2,
              f"{sorted({(h['date'], h['source_dated']) for h in got})}，{len(got)} 列")

        old_layout = [
            ["股票"],
            ["代碼", "名稱", "股數", "市值", "權重"],
            ["TW0002330008", "台灣積體電路製造", 356000, 763620000, 22.52],
            ["KYG9721M1033", "慧洋-KY", 403000, 36068500, 1.06],
        ]
        got_old = ab_parse(old_layout)
        check("聯博：舊版面（表頭「權重」＋ISIN）照樣解析，KY 股查對照表",
              [(h["stock_code"], h["shares"], h["weight"]) for h in got_old]
              == [("2330", 356000, 22.52), ("2637", 403000, 1.06)],
              f"{[(h['stock_code'], h['shares'], h['weight']) for h in got_old]}")

    try:
        from src.fsitc_scraper import FSITCScraper
    except ImportError as e:
        results.append((SKIP, "第一金 彙總列（缺套件）", str(e)[:60]))
        print(f"  [{SKIP}] 第一金 彙總列 — {str(e)[:60]}")
    else:
        # 2026-11-26 查 00408A 的實際回應（節錄）：股票列 group=1，尾端三列彙總 group=4／5
        api_rows = [
            {"fundid": "183", "sdate": "2026-11-25", "group": "1", "A": "2330", "B": "台積電", "C": "6.20", "D": "34,500", "E": ""},
            {"fundid": "183", "sdate": "2026-11-25", "group": "1", "A": "1216", "B": "統一", "C": "0.13", "D": "20,000", "E": ""},
            {"fundid": "183", "sdate": "2026-11-25", "group": "4", "A": "現金/存款", "B": "TWD 319,562,130", "C": "26.69", "D": "", "E": ""},
            {"fundid": "183", "sdate": "2026-11-25", "group": "5", "A": "股票", "B": "77.17%", "C": "1", "D": "", "E": ""},
            {"fundid": "183", "sdate": "2026-11-25", "group": "5", "A": "其他+負債", "B": "26.69%", "C": "5", "D": "", "E": ""},
        ]
        fs_rows, fs_date = FSITCScraper()._parse_json_data(api_rows, "2026-11-26", "00408A")
        check("第一金：尾端三列彙總（現金/存款、股票、其他+負債）不當成持股",
              [(h["stock_code"], h["shares"], h["weight"]) for h in fs_rows]
              == [("2330", 34500, 6.2), ("1216", 20000, 0.13)],
              f"{[(h['stock_code'], h['shares'], h['weight']) for h in fs_rows]}")
        check("第一金：資料日期仍取 sdate 並標 source_dated",
              fs_date == "2026-11-25" and bool(fs_rows)
              and all(h["date"] == "2026-11-25" and h["source_dated"] is True for h in fs_rows),
              f"actual_date={fs_date}")

    try:
        from src.ctbc_scraper import CTBCScraper
    except ImportError as e:
        results.append((SKIP, "中信 網域（缺套件）", str(e)[:60]))
        print(f"  [{SKIP}] 中信 網域 — {str(e)[:60]}")
    else:
        check("中信：持股頁走 .com.tw（.com 的頁面跨網域呼叫 API 會被擋）",
              CTBCScraper.BASE_URL == "https://www.ctbcinvestments.com.tw", CTBCScraper.BASE_URL)


def report_stock_cells(fund, caption_prefix):
    """依靜態日報中的公開個股連結定位資料列，保留海外市場後綴。"""
    from urllib.parse import parse_qs, urlsplit

    for table in fund.find_all("table") if fund else ():
        if not table.caption or not table.caption.get_text(strip=True).startswith(caption_prefix):
            continue
        by_code = {}
        for row in table.select("tbody tr"):
            link = row.select_one('th a[href]')
            if link:
                code = parse_qs(urlsplit(link["href"]).query).get("code", [""])[0]
                by_code[code] = [td.get_text("", strip=True).replace(" ", "") for td in row.find_all("td")]
        return by_code
    return {}


def check_foreign_holdings():
    """
    00988A（主動統一全球創新，2026-09-03 加入）含海外成分股。三件事不能壞：

    1. 統一 Excel 解析器要同時收「台股純數字代號」與「Bloomberg 海外代號（代號 市場）」，
       表頭／合計列仍要跳過。改回舊的「只收 4 位數字」會讓這裡變紅（實站 48 檔會被丟 39 檔）。
    2. 海外代號必須連市場後綴一起存：實測 5 檔日／港股的數字部分等於真實台股代號
       （6997 JP↔博弘、3308 HK↔聯德、6871 JP↔新鑫、5801 JP↔建弘投信、4180 JP↔安成藥）。
    3. 名稱正規化只能碰台股：`6997 JP` 不可被改名成台股 6997。

    報表層：海外部位單位標「千股」、台股維持「張」，且 JSON 帶 market 欄位。全部離線可測。
    """
    from src.stock_markets import market_of, lot_unit, normalize_code
    from src.stock_names import canonical_name

    print("--- 代號市場判定（src/stock_markets.py）---")
    check("台股純數字 -> TW／張", market_of("2330") == "TW" and lot_unit("2330") == "張")
    check("台股 ETF 尾碼字母 -> TW", market_of("00981A") == "TW")
    check("Bloomberg 海外代號 -> 市場後綴／千股",
          [market_of(c) for c in ("SNDK US", "6981 JP", "009150 KS", "3308 HK", "300408 CH", "IFX GY", "285A JP")]
          == ["US", "JP", "KS", "HK", "CH", "GY", "JP"] and lot_unit("SNDK US") == "千股")
    check("表頭／空白／期貨或選擇權描述 -> None（呼叫端跳過）",
          all(market_of(c) is None for c in ("股票代號", "nan", "", None, "FTM6", "TWSE 06/17/26 C37400")))
    check("代號正規化：壓空白、轉大寫", normalize_code(" sndk   us ") == "SNDK US")

    print("--- 名稱正規化不可碰海外代號 ---")
    tw_name = canonical_name("6997", "x")
    check("台股 6997 查得到對照名稱（前提）", tw_name != "x", f"得 {tw_name}")
    check("日股 6997 JP 維持來源名稱、不被改成台股名",
          canonical_name("6997 JP", "NIPPON CHEMI-CON CORP") == "NIPPON CHEMI-CON CORP")
    check("港股 3308 HK 同樣不被改名",
          canonical_name("3308 HK", "ZHONGJI INNOLIGHT CO LTD-H") == "ZHONGJI INNOLIGHT CO LTD-H")

    print("--- 統一 Excel 解析：海外代號要收、表頭與合計列要跳過 ---")
    try:
        import pandas as pd
        from src.ezmoney_scraper import EZMoneyScraper
    except ImportError as e:
        results.append((SKIP, "統一 Excel 海外代號解析（缺套件）", str(e)[:60]))
        print(f"  [{SKIP}] 統一 Excel 海外代號解析 — {str(e)[:60]}")
        return

    # 照抄 2026-09-03 實際下載的 61YTW Excel 版面：第 0 列資料日期、第 19 列表頭、第 20 列起持股
    layout = [["資料日期：115/09/01", None, None, None]] + [[None] * 4 for _ in range(18)] + [
        ["股票代號", "股票名稱", "股數", "持股權重"],
        ["LITE US", "LUMENTUM HOLDINGS INC", "117,000", "6.20%"],
        ["3037", "欣興", "2,600,000", "4.86%"],
        ["009150 KS", "Samsung Electro-Mechanics co(009150 ks)", "70,000", "4.36%"],
        ["6997 JP", "NIPPON CHEMI-CON CORP", "1,275,100", "1.43%"],
        ["285A JP", "KIOXIA HOLDINGS CORP", "110,000", "2.14%"],
        ["合計", None, None, "97.55%"],
    ]
    fixture = Path(tempfile.mkdtemp()) / "61YTW_fixture.xlsx"
    pd.DataFrame(layout).to_excel(fixture, index=False, header=False)
    parsed = EZMoneyScraper().parse_excel_file(fixture, "00988A", "2026-09-03")
    codes = [r["stock_code"] for r in parsed]
    check("台股與海外代號都收進來、表頭與合計列跳過",
          codes == ["LITE US", "3037", "009150 KS", "6997 JP", "285A JP"], f"codes={codes}")
    check("海外代號保留市場後綴（不是只剩數字）", "6997 JP" in codes and "6997" not in codes)
    check("股數與權重解析正確",
          bool(parsed) and parsed[0]["shares"] == 117000 and parsed[0]["weight"] == 6.2
          and parsed[3]["shares"] == 1275100)
    check("資料日期取自 Excel 表頭（民國 115/09/01）且標 source_dated",
          bool(parsed) and all(r["date"] == "2026-09-01" and r["source_dated"] is True for r in parsed))

    print("--- 報表層：海外部位標「千股」、台股標「張」、JSON 帶 market ---")
    from bs4 import BeautifulSoup
    from src.holdings_analyzer import HoldingChange
    from src.report_generator import HTMLReportGenerator
    from src.report_manager import ReportManager

    db_f, _ = fresh_db()
    db_f.insert_holdings(rows_sd("00988A", "2026-08-31", [("2330", 500000, 2.10)]))
    db_f.insert_holdings(rows_sd("00988A", "2026-09-01", [("2330", 550000, 2.58), ("SNDK US", 13000, 1.22)]))
    mgr = ReportManager(db_f, Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()))
    built = mgr.build_etf_holdings({"00988A": "主動統一全球創新"}, "2026-09-01")
    markets = {h["stock_code"]: h["market"] for h in built[0]["holdings"]} if built else {}
    check("持股總覽每列帶 market（TW／US）", markets == {"2330": "TW", "SNDK US": "US"}, f"{markets}")

    gen = HTMLReportGenerator(Path(tempfile.mkdtemp()))
    changes = {"00988A": [
        HoldingChange(change_type="ADDED", stock_code="SNDK US", stock_name="SANDISK CORP",
                      new_shares=13000, new_lots=13.0),
        HoldingChange(change_type="SHARES_UP", stock_code="2330", stock_name="台積電",
                      old_shares=500000, new_shares=550000, shares_diff=50000,
                      old_lots=500.0, new_lots=550.0, lots_diff=50.0),
    ]}
    report_path = gen.generate_daily_report(changes, "2026-09-01", {"00988A": "主動統一全球創新"}, built)
    dash = json.loads((report_path.parent / "data_2026-09-01.json").read_text(encoding="utf-8"))
    entry = dash["detailed_changes"][0]
    check("變動明細 JSON 帶 market（新增 US／變動 TW）",
          entry["added"][0]["market"] == "US" and entry["modified"][0]["market"] == "TW")
    doc = BeautifulSoup(report_path.read_text(encoding="utf-8"), "html.parser")
    fund = doc.select_one("details.fund#etf-00988A")

    holdings = report_stock_cells(fund, "完整持股")
    check("持股總覽 HTML：台股列「張」、海外列「千股」、卡片標示含海外成分股",
          holdings.get("2330", [])[-1:] == ["550張"] and holdings.get("SNDK US", [])[-1:] == ["13千股"]
          and fund and "含 1 檔海外成分股" in fund.summary.get_text(" ", strip=True))
    adjustment = report_stock_cells(fund, "兩次揭露間的持股異動")
    check("變動明細 HTML：海外新增列「千股」、台股變動列「張」",
          adjustment.get("SNDK US") == ["新增", "0千股", "13千股", "+13千股"]
          and adjustment.get("2330") == ["增持", "500張", "550張", "+50張"])
    txt = mgr.analyzer.generate_report(changes, "2026-09-01")
    check("TXT 報告：海外列「千股」、台股列「張」", "13.00千股" in txt and "550.00張" in txt)
    md = mgr.analyzer.generate_markdown_report(changes, "2026-09-01")
    check("Markdown 報告：海外列「千股」、台股列「張」", "13.00千股" in md and "550張" in md)


def check_ezmoney_layout_and_pcf_date():
    """
    00981A（統一 49YTW）2026-07-31 ~ 09-24 整串晚一個交易日的回歸測試。

    1. Excel 版面：00981A 自 7/31 起在股票表前多了一段期貨明細（5 欄），股票表頭從第 19 列
       移到第 22 列。寫死列數／欄數的解析器會把整張股票表當成非持股列跳過、每天退回 API。
    2. API 日期：GetPCF 的日期參數是 PCF 適用日（PostDate），回來的持股是前一交易日收盤
       （TranDate）。拿請求日期當資料日期，每一天都晚一個交易日，而且防護擋不到
       （每天內容都不同，只是整串平移）。備援要取最新一份並以 TranDate 當資料日期。
    """
    try:
        import pandas as pd
        from src.ezmoney_scraper import EZMoneyScraper
    except ImportError as e:
        results.append((SKIP, "統一 00981A 版面／API 日期（缺套件）", str(e)[:60]))
        print(f"  [{SKIP}] 統一 00981A 版面／API 日期 — {str(e)[:60]}")
        return

    print("--- Excel：股票表前有期貨段（5 欄）時仍要找到股票表 ---")
    # 照抄 2026-09-26 下載的 49YTW Excel 版面（資料日期 115/09/24）：
    # 第 18 列期貨表頭（5 欄）、第 22 列股票表頭、第 23 列起持股；儲存格全是字串
    blank = [None] * 5
    layout = [
        ["資料日期：115/09/24", None, None, None, None], blank,
        ["基金資產", None, None, None, None],
        ["淨資產", "NTD 290,341,568,586", None, None, None],
        ["流通在外單位數", "9,343,709,000", None, None, None],
        ["每單位淨值", "NTD 31.07", None, None, None], blank,
        ["項目", "金額", "權重", None, None],
        ["期貨(名目本金)", "NTD 6,535,375,000", "2.25%", None, None],
        ["股票", "NTD 281,741,779,235", "97.04%", None, None], blank,
        ["項目", "金額", None, None, None],
        ["現金", "NTD 7,907,071,412", None, None, None],
        ["期貨保證金", "NTD 2,141,350,397", None, None, None],
        ["附買回債券", "NTD 3,482,132,473", None, None, None],
        ["應收付證券款", "NTD 8,934,608,591", None, None, None], blank,
        ["期貨(名目本金)", None, None, None, None],
        ["期貨代號", "期貨名稱", "持股權重", "口數", "契約年月"],
        ["TX", "台指期貨", "2.25%", "679", "2026/10"], blank,
        ["股票", None, None, None, None],
        ["股票代號", "股票名稱", "股數", "持股權重", None],
        ["2330", "台積電", "11,464,000", "9.77%", None],
        ["2454", "聯發科", "5,086,000", "9.26%", None],
        ["3037", "欣興", "20,100,000", "8.20%", None],
    ]
    fixture = Path(tempfile.mkdtemp()) / "49YTW_fixture.xlsx"
    pd.DataFrame(layout).to_excel(fixture, index=False, header=False)
    parsed = EZMoneyScraper().parse_excel_file(fixture, "00981A", "2026-09-26")
    codes = [r["stock_code"] for r in parsed]
    check("股票表全部收進來、期貨列不混入", codes == ["2330", "2454", "3037"], f"codes={codes}")
    check("股數與權重取自正確欄位",
          bool(parsed) and parsed[0]["shares"] == 11464000 and parsed[0]["weight"] == 9.77
          and parsed[2]["shares"] == 20100000)
    check("資料日期取自 Excel 表頭（115/09/24）且標 source_dated",
          bool(parsed) and all(r["date"] == "2026-09-24" and r["source_dated"] is True for r in parsed))

    print("--- API 備援：資料日期用 TranDate，不用請求日期 ---")
    # 2026-09-26 實測：請求 09/24 → TranDate 09/23、PostDate 09/24；specificDate=False 取最新一份。
    # /Date(ms)/ 是台北午夜：1790092800000 ＝ 2026-09-22T16:00Z ＝ 台北 09/23（UTC 主機上不能讀成 09/22）
    tran, post = "/Date(1790092800000)/", "/Date(1790179200000)/"
    payload = {
        "pcf": [{"FundCode": "49YTW", "TranDate": tran, "PostDate": post}],
        "asset": [
            {"AssetCode": "GD", "AssetName": "期貨(名目本金)", "Details": [
                {"DetailCode": "TX", "DetailName": "台指期貨", "Share": 679, "Amount": 6560769600.0,
                 "NavRate": 2.25, "MoneyType": "NTD", "TranDate": tran}]},
            {"AssetCode": "ST", "AssetName": "股票", "Details": [
                {"DetailCode": "2330", "DetailName": "台積電", "Share": 11864000, "Amount": 29660000000.0,
                 "NavRate": 10.1, "MoneyType": "NTD", "TranDate": tran}]},
        ],
    }
    calls = []
    scraper = EZMoneyScraper()
    scraper.get_pcf_data = lambda fund_code, date, specific_date=True: (calls.append(specific_date), payload)[1]
    api_rows = scraper._get_holdings_from_api("00981A", "49YTW", "2026-09-24")
    check("API：只收股票（期貨不混入）", [r["stock_code"] for r in api_rows] == ["2330"])
    check("API：資料日期＝TranDate（台北 09/23），不是請求日 09/24",
          bool(api_rows) and all(r["date"] == "2026-09-23" for r in api_rows),
          f"dates={sorted({r['date'] for r in api_rows})}")
    check("API：以來源日期標 source_dated", bool(api_rows) and all(r.get("source_dated") is True for r in api_rows))
    check("API：備援取最新一份 PCF（specificDate=False）", calls == [False], f"specific_date={calls}")

    # 同一個請求有時回 /Date(ms)/、有時回 ISO（2026-09-26 回補時 40 次請求有 7 次是 ISO），兩種都要認得
    payload["pcf"][0]["TranDate"] = "2026-09-23T00:00:00"
    for d in payload["asset"][1]["Details"]:
        d["TranDate"] = "2026-09-23T00:00:00"
    iso_rows = scraper._get_holdings_from_api("00981A", "49YTW", "2026-09-24")
    check("API：TranDate 為 ISO 格式時同樣取用並標 source_dated",
          bool(iso_rows) and all(r["date"] == "2026-09-23" and r.get("source_dated") is True for r in iso_rows),
          f"dates={sorted({r['date'] for r in iso_rows})}")

    payload["pcf"] = []
    for d in payload["asset"][1]["Details"]:
        d.pop("TranDate")
    no_date = scraper._get_holdings_from_api("00981A", "49YTW", "2026-09-24")
    check("API：沒有 TranDate -> 退回請求日且不標 source_dated（防護繼續生效）",
          bool(no_date) and all(r["date"] == "2026-09-24" and not r.get("source_dated") for r in no_date))


def check_upsert_created_at():
    """
    UPSERT 的 created_at 語意：「該列首次寫入時間」。

    停更重寫（source_dated 豁免下，同一個資料日期整組重寫）不可刷新 created_at，
    否則 CI 早退守衛會把「來源沒更新」算成今天有進度；豁免檔數過 70% 門檻後
    （第二批轉換後 14/19；2026-08-09 新增兆豐／凱基／永豐後 17/22；
    2026-09-03 新增 00988A（統一 Excel 路徑）後 18/23），
    「全來源停更」的傍晚會誤跳過後備班次。
    這組測試對舊實作（INSERT OR REPLACE）是紅的。
    """
    db, _ = fresh_db()
    db.insert_holdings(rows_sd("00982A", "2026-08-04", DAY1))
    conn = db.get_connection()
    # 模擬「這些列是昨天寫入的」
    conn.execute("update holdings set created_at='2026-08-04 10:25:00'")
    conn.commit()

    # 停更重寫：同一天、同內容再寫一次
    db.insert_holdings(rows_sd("00982A", "2026-08-04", DAY1))
    stamps = [r[0] for r in db.get_connection().execute(
        "select distinct created_at from holdings where etf_code='00982A'")]
    check("停更重寫不刷新 created_at（守衛不會誤計）",
          stamps == ["2026-08-04 10:25:00"], f"created_at={stamps}")

    # 數值變動的更新也保留首次寫入時間，且數值要真的更新
    db.insert_holdings(rows_sd("00982A", "2026-08-04", DAY2_CHANGED))
    row = db.get_connection().execute(
        "select shares, created_at from holdings "
        "where etf_code='00982A' and stock_code='2330' and date='2026-08-04'"
    ).fetchone()
    check("內容更新生效但 created_at 仍是首次寫入時間",
          row == (46500, "2026-08-04 10:25:00"), f"row={row}")

    # 守衛的 WROTE 查詢：昨天首寫的列今天重寫後，不得計入「今天」
    wrote_today = db.get_connection().execute(
        "select count(distinct etf_code) from holdings "
        "where substr(created_at,1,10)=date('now')").fetchone()[0]
    check("守衛 WROTE 查詢不把停更重寫計入今天", wrote_today == 0, f"WROTE={wrote_today}")

    # 新的一天首次寫入照常計入
    db.insert_holdings(rows_sd("00982A", "2026-08-05", DAY2_CHANGED))
    wrote_today = db.get_connection().execute(
        "select count(distinct etf_code) from holdings "
        "where substr(created_at,1,10)=date('now')").fetchone()[0]
    check("新資料日期的首次寫入計入今天", wrote_today == 1, f"WROTE={wrote_today}")


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
    # 沒有這個欄位，首頁的跨報表彙總就無法去重，同一次調整會被重複計入買賣張數。
    dc = {e["etf_code"]: e.get("data_date") for e in data["detailed_changes"]}
    check("變動清單每筆都帶 data_date", all(dc.values()), f"detailed_changes={dc}")
    check("變動清單：落後那檔標自己的資料日期 8/4",
          dc.get("00995A") == "2026-08-04", f"data_date={dc.get('00995A')}")

    # 回填腳本必須共用同一個報表出口。它曾經自己組一份持股總覽（單一日期、無 data_date），
    # 導致回填出來的報表掉了 data_date，且兩半各用一套日期規則；後來又是「每檔取不晚於報表日期的
    # 最新資料」的整份重生，會把固定落後一天的來源整串往前平移。現在只准轉交給 pinned_reports。
    regen = (Path(__file__).parent / "scripts" / "regenerate_reports.py").read_text(
        encoding="utf-8")
    check("回填腳本轉交給 pinned_reports.regenerate（資料日期固定在發布當時的值）",
          "pinned_reports.regenerate(" in regen and "refresh_etfs=" in regen)
    check("回填腳本沒有自己組持股總覽、也沒有自己呼叫產生器",
          '"stock_code": h.get' not in regen and "build_etf_holdings" not in regen
          and "generate_daily_report" not in regen)


def check_stale_etfs_not_repeated():
    """
    來源沒有新資料的 ETF：變動只在資料日期第一次出現的那份報表列一次，之後改列在「今日沒有新資料」。

    變動是逐檔比對「各自最新可得的資料日期」得出的，來源停更時 detect_changes_batch 每天都回同一批變動。
    2026-11 中信、聯博、兆豐停更期間，每日報表有 25～57% 的變動是這種 2～5 週前的舊資料，看起來卻像當天的。
    這裡照時間順序重演兩個傍晚：00996A（兆豐的形狀）第二天沒有新資料，00994A（固定落後一天的來源）
    兩天的資料日期都比報表早一天、但每天都有前進，00981A 每天都有當日資料。
    """
    from src.report_manager import ReportManager

    work = Path(tempfile.mkdtemp())
    db = Database(str(work / "t.db"))
    codes = ["00981A", "00994A", "00996A"]
    db.insert_etf_list([{"etf_code": c, "etf_name": f"名稱{c}", "issuer": ""} for c in codes])
    mgr = ReportManager(db, work / "reports", work / "docs")

    def publish(date, **kwargs):
        mgr.generate_all_reports(mgr.analyzer.detect_changes_batch(codes, date), date, append_txt=False, **kwargs)
        return json.loads((work / "docs" / f"data_{date}.json").read_text(encoding="utf-8"))

    # 11-24 傍晚：三檔都有新資料（00994A 的最新是 11-23，落後一天屬正常）
    db.insert_holdings(rows_sd("00981A", "2026-11-23", DAY1))
    db.insert_holdings(rows_sd("00981A", "2026-11-24", DAY2_CHANGED))
    db.insert_holdings(rows_sd("00996A", "2026-11-23", DAY1))
    db.insert_holdings(rows_sd("00996A", "2026-11-24", DAY2_CHANGED))
    db.insert_holdings(rows_sd("00994A", "2026-11-20", DAY1))
    db.insert_holdings(rows_sd("00994A", "2026-11-23", DAY2_CHANGED))
    first = publish("2026-11-24")
    check("第一份報表：三檔的變動都列出，沒有 stale_etfs 欄位（輸出與加這個功能之前相同）",
          [e["etf_code"] for e in first["detailed_changes"]] == codes and "stale_etfs" not in first,
          f"changes={[e['etf_code'] for e in first['detailed_changes']]} keys={sorted(first)}")

    # 11-25 傍晚：00981A 有當日資料、00994A 前進到 11-24、00996A 沒有新資料
    db.insert_holdings(rows_sd("00981A", "2026-11-25", DAY1))
    db.insert_holdings(rows_sd("00994A", "2026-11-24", DAY1))
    second = publish("2026-11-25")
    check("沒有新資料的 ETF：變動不重列",
          [e["etf_code"] for e in second["detailed_changes"]] == ["00981A", "00994A"],
          f"changes={[e['etf_code'] for e in second['detailed_changes']]}")
    check("沒有新資料的 ETF：列在 stale_etfs，帶資料日期與落後的交易日數",
          second.get("stale_etfs") == [{"etf_code": "00996A", "etf_name": "名稱00996A",
                                        "data_date": "2026-11-24", "trading_days_behind": 1}],
          f"{second.get('stale_etfs')}")
    check("固定落後一天但有前進的來源不算停更，變動照列且標自己的資料日期",
          {e["etf_code"]: e["data_date"] for e in second["detailed_changes"]}.get("00994A") == "2026-11-24")
    check("沒有新資料的 ETF 仍留在持股總覽（最後一次抓到的內容）",
          {e["etf_code"]: e["data_date"] for e in second["etf_holdings"]}.get("00996A") == "2026-11-24")
    check("摘要與索引只算有新資料的 ETF",
          second["summary"]["total_etfs"] == 2
          and json.loads((work / "docs" / "reports_index.json").read_text(encoding="utf-8"))[0]["etfs"]
          == ["00981A", "00994A"], f"summary={second['summary']}")
    md = (work / "reports" / "changes_2026-11-25.md").read_text(encoding="utf-8")
    txt = (work / "reports" / "changes_2026-11-25.txt").read_text(encoding="utf-8")
    html = (work / "docs" / "report_2026-11-25.html").read_text(encoding="utf-8")
    check("三種格式都標出沒有新資料的 ETF",
          "今日沒有新資料的 ETF" in md and "| 00996A |" in md and "**本日共 2 檔 ETF" in md
          and "今日沒有新資料的 ETF (1)" in txt and "00996A" in txt
          and "1 檔 ETF 今日沒有新資料" in html and "今日未更新" in html)

    # 同一天稍晚補到 00996A 的 11-25（本機回補），重生同一份報表：變動要出現、不再標停更
    db.insert_holdings(rows_sd("00996A", "2026-11-25", DAY1))
    refreshed = publish("2026-11-25")
    check("補到資料後重生同一份報表：變動列出、stale_etfs 消失",
          [e["etf_code"] for e in refreshed["detailed_changes"]] == codes and "stale_etfs" not in refreshed,
          f"changes={[e['etf_code'] for e in refreshed['detailed_changes']]} keys={sorted(refreshed)}")

    # 工具重生歷史報表時自己給上一份報表的資料日期（不讀 docs 目錄）
    forced = publish("2026-11-25", previous_data_dates={"00981A": "2026-11-25"})
    check("previous_data_dates 由呼叫端指定時照指定的判斷",
          [e["etf_code"] for e in forced["detailed_changes"]] == ["00994A", "00996A"]
          and [e["etf_code"] for e in forced.get("stale_etfs", [])] == ["00981A"],
          f"changes={[e['etf_code'] for e in forced['detailed_changes']]}")


def check_report_comparison_periods():
    """日報分別保留來源比較日與上一份報表可見的日期，包含首次、無異動與跨期後恢復。"""
    from urllib.parse import parse_qs, urlsplit

    from bs4 import BeautifulSoup
    from src.report_manager import ReportManager

    work = Path(tempfile.mkdtemp())
    db = Database(str(work / "holdings.db"))
    docs = work / "docs"
    mgr = ReportManager(db, work / "reports", docs)
    codes = ["00404A", "00981A", "00985A", "00988A"]
    db.insert_etf_list([{"etf_code": code, "etf_name": code, "issuer": ""} for code in codes])
    db.insert_holdings(rows_sd("00404A", "2026-11-10", DAY1))
    db.insert_holdings(rows_sd("00981A", "2026-11-17", [("2330", 1000, 1.0)]))
    db.insert_holdings(rows_sd("00985A", "2026-11-17", DAY1))
    mgr.generate_all_reports({}, "2026-11-17")
    first = read_report(docs, "2026-11-17")
    check("首次持股可發日報，缺比較基準與無異動分開",
          first["summary"]["total_changes"] == 0 and first["previous_report_date"] is None
          and all(e["comparison_kind"] == "first" for e in first["etf_holdings"]))

    db.insert_holdings(rows_sd("00404A", "2026-11-18", DAY2_CHANGED))
    db.insert_holdings(rows_sd("00981A", "2026-11-18", [("2330", 1001, 1.0)]))
    db.insert_holdings(rows_sd("00985A", "2026-11-18", DAY1))
    db.insert_holdings(rows_sd("00988A", "2026-11-18", [("3308 HK", 1001, 1.0)]))
    # 單獨抓一家投信時，呼叫端只計算了這一家的異動；整站日報仍須補齊其他 ETF。
    mgr.generate_all_reports(mgr.analyzer.detect_changes_batch(["00404A"], "2026-11-18"), "2026-11-18")
    second = read_report(docs, "2026-11-18")
    funds = {e["etf_code"]: e for e in second["etf_holdings"]}
    event = next(e for e in second["detailed_changes"] if e["etf_code"] == "00981A")["modified"][0]
    check("逐檔前次持股日：跨期從 11/10 起，日資料從 11/17 起",
          second["report_schema_version"] == 2 and second["previous_trading_date"] == "2026-11-17"
          and second["previous_report_date"] == "2026-11-17"
          and funds["00404A"]["comparison_kind"] == "interval"
          and funds["00404A"]["previous_data_date"] == funds["00404A"]["previous_report_data_date"] == "2026-11-10"
          and funds["00985A"]["comparison_kind"] == "daily" and funds["00985A"]["previous_data_date"] == "2026-11-17"
          and funds["00988A"]["comparison_kind"] == "first" and funds["00988A"]["previous_data_date"] is None)
    check("單股增減保留三位小數與正確增減方向", event["diff"] == 0.001 and event["direction"] == "up"
          and event["old_lots"] == 1 and event["new_lots"] == 1.001)
    html = (docs / "report_2026-11-18.html").read_text(encoding="utf-8")
    page = BeautifulSoup(html, "html.parser")
    styles = {link.get("href", "").removeprefix("./") for link in page.select('link[rel="stylesheet"]')}
    article = page.select_one('main.frame #content > article#daily-report[data-report-date="2026-11-18"]')
    nav = page.select_one('.masthead .primary-nav')
    check("新產製日報沿用全站品牌、主題、日期與搜尋，靜態揭露仍可單獨閱讀",
          {'assets/site.css', 'assets/report.css'} <= styles
          and page.select_one('.masthead .topbar.frame .brand') and nav
          and len(nav.select('a[data-view]')) == 6 and nav.select_one('[data-view="report"][aria-current="page"]')
          and page.select_one('.masthead [data-theme-choice="light"][aria-label="白天模式"]')
          and page.select_one('.masthead [data-theme-choice="dark"][aria-label="夜間模式"]')
          and page.select_one('#open-search') and page.select_one('dialog#search-dialog')
          and page.select_one('#report-date option[value="2026-11-18"]')
          and page.select_one('noscript time[datetime="2026-11-18"]')
          and article and article.select_one('h1') and article.h1.get_text(strip=True) == '持股日報'
          and article.select_one('#activity') and article.select_one('#funds details.fund#etf-00404A table'))

    def destination(link):
        url = urlsplit(link['href'])
        return (url.path.removeprefix('./'), parse_qs(url.query))

    overview = nav.select_one('[data-view="overview"]') if nav else None
    links = [destination(a) for a in article.select('a[href]')] if article else []
    check("靜態日報可開同日 ETF、完整海外股票代號與兩期變動",
          overview and destination(overview) == ('index.html', {'date': ['2026-11-18']})
          and all(('index.html', {'date': ['2026-11-18'], 'view': [view], 'code': [code]}) in links
                  for view, code in [('etf', '00404A'), ('stock', '3308 HK')])
          and '2026-11-10 → 2026-11-18 · 跨期比較' in article.get_text())

    archive = Path(__file__).resolve().parent / "docs" / "report_2026-02-06.html"
    published = BeautifulSoup(archive.read_text(encoding="utf-8"), "html.parser")
    february_changes = report_stock_cells(published.select_one("details.fund#etf-00994A"), "兩次揭露間的持股異動")
    check("2/6 已發布日報：00994A 的 4904 實增 1 股，方向與互動頁一致",
          february_changes.get("4904") == ["增持", "1.002張", "1.003張", "+0.001張"],
          f"4904={february_changes.get('4904')}")

    mgr.generate_all_reports(mgr.analyzer.detect_changes_batch(codes, "2026-11-19"), "2026-11-19")
    check("所有資料沿用前期時不新增空日報", not (docs / "data_2026-11-19.json").exists())

    db.insert_holdings(rows_sd("00985A", "2026-11-19", DAY1))
    mgr.generate_all_reports(mgr.analyzer.detect_changes_batch(codes, "2026-11-19"), "2026-11-19")
    third = read_report(docs, "2026-11-19")
    check("有新來源、可比持股完全相同時仍有零異動日報",
          third["summary"]["total_changes"] == 0 and "兩期持股數量相同" in
          (docs / "report_2026-11-19.html").read_text(encoding="utf-8"))


DAY3 = [("2330", 47000, 6.35), ("2454", 19000, 4.30), ("2317", 8000, 2.10)]


def load_script(name):
    """載入 scripts/ 底下的模組（scripts 目錄不是套件；回補腳本自己也會 import pinned_reports）"""
    import importlib

    scripts_dir = str(Path(__file__).parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    return importlib.import_module(name)


def published_stale_scenario():
    """
    三個傍晚照時間順序發布、之後才補到資料的現場（兆豐被擋在 runner 外的形狀）：

    - 00981A 每天都有當日資料。
    - 00994A 固定落後一天：每份報表的資料日期都是前一個交易日。12-01 的持股在 12-01 的報表發布之後才進 DB。
    - 00996A 在 11-27 之後就沒有新資料，11-30、12-01 兩份報表都把它列在「沒有新資料」。

    回傳 (work, db, db_path, docs, reports, mgr)。發布之後 DB 多了 00994A 的 12-01；00996A 還沒補。
    """
    from src.report_manager import ReportManager

    work = Path(tempfile.mkdtemp())
    db_path = work / "t.db"
    db = Database(str(db_path))
    codes = ["00981A", "00994A", "00996A"]
    db.insert_etf_list([{"etf_code": c, "etf_name": f"名稱{c}", "issuer": ""} for c in codes])
    docs, reports = work / "docs", work / "reports"
    mgr = ReportManager(db, reports, docs)

    def publish(date):
        mgr.generate_all_reports(mgr.analyzer.detect_changes_batch(codes, date), date, append_txt=False)

    db.insert_holdings(rows_sd("00981A", "2026-11-26", DAY1))
    db.insert_holdings(rows_sd("00981A", "2026-11-27", DAY2_CHANGED))
    db.insert_holdings(rows_sd("00994A", "2026-11-25", DAY1))
    db.insert_holdings(rows_sd("00994A", "2026-11-26", DAY2_CHANGED))
    db.insert_holdings(rows_sd("00996A", "2026-11-26", DAY1))
    db.insert_holdings(rows_sd("00996A", "2026-11-27", DAY2_CHANGED))
    publish("2026-11-27")
    db.insert_holdings(rows_sd("00981A", "2026-11-30", DAY1))
    db.insert_holdings(rows_sd("00994A", "2026-11-27", DAY1))
    publish("2026-11-30")
    db.insert_holdings(rows_sd("00981A", "2026-12-01", DAY2_CHANGED))
    db.insert_holdings(rows_sd("00994A", "2026-11-30", DAY2_CHANGED))
    publish("2026-12-01")
    db.insert_holdings(rows_sd("00994A", "2026-12-01", DAY1))   # 隔天早上才到，12-01 的報表已經發布
    return work, db, db_path, docs, reports, mgr


def read_report(docs, date):
    return json.loads((docs / f"data_{date}.json").read_text(encoding="utf-8"))


def check_pinned_regeneration():
    """
    scripts/pinned_reports.py：事後補進某一檔的持股時，只有那一檔用新資料重生報表。

    不能整份重生：固定落後一天的來源（第一金、00988A）事後 DB 已經補齊，整份重生會把它們在舊報表裡的
    資料日期一起往前推，原本那一天的變動就不在任何報表裡了。這裡照時間順序發布三份報表，之後才補到
    00996A 的 11-30、12-01，確認：只有 00996A 換成新資料、00994A 留在發布當時的資料日期、沒指定的 ETF
    在 DB 裡被動過時整份不寫回、用舊規則發布（把同一批變動再列一次）的報表重生後改成標示。
    """
    pinned = load_script("pinned_reports")
    work, db, db_path, docs, reports, mgr = published_stale_scenario()
    all_dates = ["2026-11-27", "2026-11-30", "2026-12-01"]
    paths = dict(db_path=db_path, docs_dir=docs, reports_dir=reports)

    def data_dates(payload):
        return {e["etf_code"]: e["data_date"] for e in payload["etf_holdings"]}

    def changed(payload):
        return [e["etf_code"] for e in payload["detailed_changes"]]

    before = read_report(docs, "2026-12-01")
    check("發布當時（前提）：00996A 兩份報表都列在沒有新資料、00994A 的資料日期落後一天",
          [e["etf_code"] for e in before.get("stale_etfs", [])] == ["00996A"]
          and data_dates(before) == {"00981A": "2026-12-01", "00994A": "2026-11-30", "00996A": "2026-11-27"},
          f"stale={before.get('stale_etfs')} dates={data_dates(before)}")

    control = pinned.regenerate(all_dates, **paths, write=False)
    check("對照：不指定 ETF 時三份報表重生後與發布版逐位元組相同（00994A 晚到的 12-01 沒有漏進去）",
          [(r["status"], r["identical_bytes"]) for r in control] == [("unchanged", True)] * 3,
          f"{[(r['date'], r['status'], r['identical_bytes'], r['problems']) for r in control]}")

    # 本機回補：00996A 的 11-30、12-01
    db.insert_holdings(rows_sd("00996A", "2026-11-30", DAY1))
    db.insert_holdings(rows_sd("00996A", "2026-12-01", DAY3))
    saved = {name: (docs / name).read_bytes() for name in ("data_2026-11-30.json", "data_2026-12-01.json")}
    dry = pinned.regenerate(all_dates[1:], ["00996A"], **paths, write=False)
    check("試跑（write=False）：通過核對但不寫回",
          [r["status"] for r in dry] == ["verified", "verified"]
          and all((docs / name).read_bytes() == content for name, content in saved.items()),
          f"{[(r['date'], r['status'], r['problems']) for r in dry]}")

    outcome = pinned.regenerate(all_dates[1:], ["00996A"], **paths)
    first, second = read_report(docs, "2026-11-30"), read_report(docs, "2026-12-01")
    check("補資料後重生：兩份都寫回",
          [r["status"] for r in outcome] == ["written", "written"],
          f"{[(r['date'], r['status'], r['problems']) for r in outcome]}")
    check("指定的 00996A 換成各自報表日期的資料，變動列出、不再標沒有新資料",
          data_dates(first)["00996A"] == "2026-11-30" and data_dates(second)["00996A"] == "2026-12-01"
          and "00996A" in changed(first) and "00996A" in changed(second)
          and "stale_etfs" not in first and "stale_etfs" not in second,
          f"dates={data_dates(first)} / {data_dates(second)} changes={changed(first)} / {changed(second)}")
    check("沒指定的 00994A 留在發布當時的資料日期（不被晚到的 12-01 往前推）",
          data_dates(first)["00994A"] == "2026-11-27" and data_dates(second)["00994A"] == "2026-11-30",
          f"{data_dates(first)['00994A']} / {data_dates(second)['00994A']}")
    index = {row["date"]: row for row in json.loads((docs / "reports_index.json").read_text(encoding="utf-8"))}
    written = [docs / "data_2026-12-01.json", docs / "report_2026-12-01.html", docs / "reports_index.json",
               reports / "changes_2026-12-01.md", reports / "changes_2026-12-01.txt"]
    check("索引跟著更新、四種檔案都重寫且行尾是 LF",
          index["2026-12-01"]["etfs"] == ["00981A", "00994A", "00996A"]
          and index["2026-12-01"]["total_changes"] == second["summary"]["total_changes"]
          and all(b"\r\n" not in p.read_bytes() for p in written)
          and "00996A" in (reports / "changes_2026-12-01.md").read_text(encoding="utf-8")
          and "今日未更新" not in (docs / "report_2026-12-01.html").read_text(encoding="utf-8"),
          f"index={index['2026-12-01']}")
    again = pinned.regenerate(all_dates, ["00996A"], **paths)
    check("再跑一次：內容相同就不寫回，重生結果逐位元組相同",
          [(r["status"], r["identical_bytes"]) for r in again] == [("unchanged", True)] * 3,
          f"{[(r['date'], r['status'], r['identical_bytes']) for r in again]}")

    # 只補到一半：12-01 那天來源查不到
    half = Path(tempfile.mkdtemp())
    shutil.copytree(docs, half / "docs")
    shutil.copytree(reports, half / "reports")
    shutil.copy(db_path, half / "t.db")
    half_con = Database(str(half / "t.db")).get_connection()   # get_connection() 每次都開新連線，刪除與 commit 要用同一條
    half_con.execute("delete from holdings where etf_code='00996A' and date='2026-12-01'")
    half_con.commit()
    half_con.close()
    half_paths = dict(db_path=half / "t.db", docs_dir=half / "docs", reports_dir=half / "reports")
    half_outcome = pinned.regenerate(all_dates[1:], ["00996A"], **half_paths)
    partial = read_report(half / "docs", "2026-12-01")
    check("只補到 11-30：12-01 的報表改標「沒有新資料」，資料日期是 11-30、落後 1 個交易日",
          [r["status"] for r in half_outcome] == ["unchanged", "written"]
          and partial.get("stale_etfs") == [{"etf_code": "00996A", "etf_name": "名稱00996A",
                                             "data_date": "2026-11-30", "trading_days_behind": 1}]
          and "00996A" not in changed(partial),
          f"{[(r['status'], r['problems']) for r in half_outcome]} {partial.get('stale_etfs')} changes={changed(partial)}")

    # 沒指定的 ETF 在 DB 裡被動過：整份不寫回，後面的日期也不處理
    con = db.get_connection()
    con.execute("update holdings set shares=shares+1000 where etf_code='00981A' and date='2026-11-30' "
                "and stock_code='2330'")
    con.commit()
    saved = {p: p.read_bytes() for p in sorted(docs.glob("*")) + sorted(reports.glob("*"))}
    failed = pinned.regenerate(all_dates[1:], ["00996A"], **paths)
    check("沒指定的 ETF 與發布版不同 -> failed、點名是哪一檔、檔案一個都沒動、後面的日期不處理",
          [r["status"] for r in failed] == ["failed", "skipped"]
          and any("00981A" in p for p in failed[0]["problems"])
          and all(p.read_bytes() == content for p, content in saved.items()),
          f"{[(r['date'], r['status'], r['problems']) for r in failed]}")
    refreshed = pinned.regenerate(all_dates[1:], refresh_etfs=["00981A"], **paths)
    after = read_report(docs, "2026-11-30")
    lots = {h["stock_code"]: h["lots"] for e in after["etf_holdings"] if e["etf_code"] == "00981A"
            for h in e["holdings"]}
    check("refresh_etfs：資料日期不動，內容照 DB 現在的值重畫",
          refreshed[0]["status"] == "written" and data_dates(after)["00981A"] == "2026-11-30"
          and lots.get("2330") == (DAY1[0][1] + 1000) / 1000,
          f"status={refreshed[0]['status']} problems={refreshed[0]['problems']} lots={lots.get('2330')}")

    # 舊規則發布的報表：00996A 沒有新資料，卻把 11-30 -> 12-01 的變動再列一次
    db.insert_holdings(rows_sd("00981A", "2026-12-02", DAY1))
    mgr.generate_all_reports(mgr.analyzer.detect_changes_batch(["00981A", "00994A", "00996A"], "2026-12-02"),
                             "2026-12-02", append_txt=False, previous_data_dates={}, report_schema=1)
    old_rule = read_report(docs, "2026-12-02")
    check("舊規則發布（前提）：沒有新資料的 00996A 仍列出變動、沒有 stale_etfs",
          "00996A" in changed(old_rule) and "stale_etfs" not in old_rule
          and "report_schema_version" not in old_rule and data_dates(old_rule)["00996A"] == "2026-12-01",
          f"changes={changed(old_rule)}")
    tampered = json.loads(json.dumps(old_rule))
    next(e for e in tampered["detailed_changes"] if e["etf_code"] == "00996A")["modified"][0]["diff"] += 5
    (docs / "data_2026-12-02.json").write_text(json.dumps(tampered, ensure_ascii=False, indent=2), encoding="utf-8")
    not_a_repeat = pinned.regenerate(["2026-12-02"], **paths)
    check("發布版列的不是同一批變動（內容對不起來）-> 不當成重列，failed",
          not_a_repeat[0]["status"] == "failed", f"{not_a_repeat[0]['status']} {not_a_repeat[0]['notes']}")
    (docs / "data_2026-12-02.json").write_text(json.dumps(old_rule, ensure_ascii=False, indent=2), encoding="utf-8")
    cleaned = pinned.regenerate(["2026-12-02"], **paths)
    new_rule = read_report(docs, "2026-12-02")
    check("舊規則發布的報表重生後：同一批變動拿掉、改列在 stale_etfs，其他 ETF 不變",
          cleaned[0]["status"] == "written" and changed(new_rule) == ["00981A", "00994A"]
          and [e["etf_code"] for e in new_rule.get("stale_etfs", [])] == ["00996A"],
          f"{cleaned[0]['status']} {cleaned[0]['problems']} changes={changed(new_rule)}")
    legacy_control = pinned.regenerate(["2026-12-02"], **paths, write=False)
    check("舊 JSON 與舊 HTML 日報依發布時格式重生可逐位元組重現",
          "report_schema_version" not in new_rule and legacy_control[0]["identical_bytes"] is True)

    # 補產生當天沒有發布的報表
    db.insert_holdings(rows_sd("00981A", "2026-12-03", DAY3))
    skipped = pinned.regenerate(["2026-12-03"], **paths)
    created = pinned.regenerate(["2026-12-03"], **paths, create_missing=True)
    made = read_report(docs, "2026-12-03") if (docs / "data_2026-12-03.json").exists() else {}
    check("沒發布過的日期預設略過；create_missing 才補產生，每檔取不晚於那一天的最新資料",
          skipped[0]["status"] == "skipped" and created[0]["status"] == "created"
          and changed(made) == ["00981A"]
          and [e["etf_code"] for e in made.get("stale_etfs", [])] == ["00994A", "00996A"]
          and json.loads((docs / "reports_index.json").read_text(encoding="utf-8"))[0]["date"] == "2026-12-03",
          f"{skipped[0]['status']} / {created[0]['status']} {created[0]['problems']} changes={changed(made) if made else None}")


def check_megafunds_local_backfill():
    """
    本機回補兆豐（scripts/backfill_megafunds.py）與它用到的歷史查詢、交易日換算。

    兆豐的 `qdt` 是 PCF 適用日＝持股基準日的下一個交易日，查錯一天就把別天的持股寫成這一天。
    這裡不連網：頁面與 scraper 都用替身，確認查詢日期跨假日也算對、頁面標的基準日不符就不收、
    回補只補缺的交易日、補完重生的是已發布的那幾份報表。
    """
    from datetime import date

    from bs4 import BeautifulSoup
    from src.megafunds_scraper import MegaFundsScraper
    from src.trading_calendar import next_trading_day, trading_days_between

    check("下一個交易日：跳過週末與連假（09-24 -> 09-29，11-27 週五 -> 11-30）",
          next_trading_day(date(2026, 9, 24)) == date(2026, 9, 29)
          and next_trading_day(date(2026, 11, 27)) == date(2026, 11, 30)
          and next_trading_day(date(2026, 11, 28)) == date(2026, 11, 30))
    check("兩個日期之間的交易日數：不含起日、含迄日，休市日不算；迄日不晚於起日是 0",
          trading_days_between(date(2026, 9, 24), date(2026, 9, 29)) == 1
          and trading_days_between(date(2026, 11, 23), date(2026, 11, 27)) == 4
          and trading_days_between(date(2026, 11, 27), date(2026, 11, 27)) == 0
          and trading_days_between(date(2026, 11, 27), date(2026, 11, 20)) == 0)

    def page(data_date):
        return BeautifulSoup(
            f'<p>查詢日期 2026/09/29 {data_date} 每基數實際申購總價金(元) TWD$ 6,654,001</p>'
            '<table class="table-stock">'
            '<tr><td>股票代號</td><td>股票名稱</td><td>股數</td><td>持股權重</td></tr>'
            '<tr><td>2330</td><td>台積電</td><td>179,000</td><td>9.95%</td></tr></table>', 'html.parser')

    scraper = MegaFundsScraper()
    asked = []

    def fake_fetch(pages):
        def fetch(etf_code, fund_id, qdt=''):
            asked.append(qdt)
            return pages.get(qdt)
        return fetch

    scraper._fetch_fund_page = fake_fetch({"2026/09/29": page("2026/09/24")})
    got = scraper.get_holdings_for_data_date("00996A", "2026-09-24")
    check("歷史查詢：基準日 09-24 要查 qdt=2026/09/29（中秋連假後的第一個交易日）",
          asked == ["2026/09/29"] and len(got) == 1 and got[0]["date"] == "2026-09-24"
          and got[0]["source_dated"] is True and got[0]["shares"] == 179000, f"qdt={asked} rows={got}")
    scraper._fetch_fund_page = fake_fetch({"2026/09/24": page("2026/09/22")})
    check("歷史查詢：頁面標的基準日不是要的那一天 -> 回空，不把別天的內容寫成這一天",
          scraper.get_holdings_for_data_date("00996A", "2026-09-23") == [])
    scraper._fetch_fund_page = fake_fetch({})
    check("歷史查詢：頁面拿不到 -> 回空", scraper.get_holdings_for_data_date("00996A", "2026-09-23") == [])

    backfill = load_script("backfill_megafunds")

    class FakeMega:
        """替身：latest 是最新一份清單的 (基準日, 持股)，history 是 {基準日: 持股}"""

        def __init__(self, latest, history):
            self.latest, self.history, self.asked = latest, history, []

        def get_etf_holdings(self, etf_code, request_date):
            return rows_sd(etf_code, self.latest[0], self.latest[1]) if self.latest else []

        def get_holdings_for_data_date(self, etf_code, data_date):
            self.asked.append(data_date)
            items = self.history.get(data_date)
            return rows_sd(etf_code, data_date, items) if items else []

    def run(scraper_, scenario, today=date(2026, 12, 1), **kwargs):
        _, _, db_path, docs, reports, _ = scenario
        said = []
        result = backfill.run(scraper_, db_path, docs, reports, today, pause_seconds=0, say=said.append, **kwargs)
        return result, said

    def mega_dates(scenario):
        return [r[0] for r in scenario[1].get_connection().execute(
            "select distinct date from holdings where etf_code='00996A' order by 1")]

    scenario = published_stale_scenario()
    mega = FakeMega(("2026-12-01", DAY3), {"2026-11-30": DAY1})
    dry, _ = run(mega, scenario, dry_run=True)
    check("試跑：列出要補的日子、什麼都不寫",
          dry["ok"] and dry["inserted"] == [] and mega_dates(scenario) == ["2026-11-26", "2026-11-27"], f"{dry}")
    mega.asked.clear()
    result, said = run(mega, scenario)
    docs = scenario[3]
    check("回補：補上 DB 最後一天之後到來源最新日的每個交易日，最新那天不重複查",
          result["ok"] and result["inserted"] == ["2026-11-30", "2026-12-01"] and result["missing"] == []
          and mega.asked == ["2026-11-30"]
          and mega_dates(scenario) == ["2026-11-26", "2026-11-27", "2026-11-30", "2026-12-01"],
          f"{result} asked={mega.asked}")
    latest_report = read_report(docs, "2026-12-01")
    check("回補後只重生受影響的已發布報表（11-30、12-01），00996A 的變動列出、不再標沒有新資料",
          result["reports"] == [{"date": "2026-11-30", "status": "written"},
                                {"date": "2026-12-01", "status": "written"}]
          and "stale_etfs" not in latest_report
          and "00996A" in [e["etf_code"] for e in latest_report["detailed_changes"]]
          and {e["etf_code"]: e["data_date"] for e in latest_report["etf_holdings"]}["00994A"] == "2026-11-30",
          f"{result['reports']}")
    again, said = run(mega, scenario)
    check("再跑一次：沒有要補的資料，成功結束",
          again["ok"] and again["inserted"] == [] and again["reports"] == [] and "沒有要補的資料" in said[-1], f"{again}")

    scenario = published_stale_scenario()
    result, _ = run(FakeMega(None, {}), scenario)
    check("抓不到最新一份清單 -> 失敗，什麼都不寫",
          not result["ok"] and mega_dates(scenario) == ["2026-11-26", "2026-11-27"], f"{result}")
    result, _ = run(FakeMega(("2026-12-02", DAY3), {}), scenario)
    check("頁面標的基準日晚於最近一個交易日 -> 失敗，什麼都不寫",
          not result["ok"] and mega_dates(scenario) == ["2026-11-26", "2026-11-27"], f"{result}")
    result, _ = run(FakeMega(("2026-12-01", DAY3), {"2026-11-30": DAY1}), scenario, max_days=1)
    check("要補的天數超過上限 -> 失敗，什麼都不寫",
          not result["ok"] and mega_dates(scenario) == ["2026-11-26", "2026-11-27"], f"{result}")
    result, _ = run(FakeMega(("2026-12-01", DAY3), {}), scenario)
    check("中間有一天來源查不到：補得到的照補，結果標失敗並列出缺的日子",
          not result["ok"] and result["inserted"] == ["2026-12-01"] and result["missing"] == ["2026-11-30"]
          and mega_dates(scenario) == ["2026-11-26", "2026-11-27", "2026-12-01"], f"{result}")


def check_holiday_dates():
    """
    國定假日要比照週末，請求日期與報表日期都退回最近一個交易日。

    main.py 原本只避開週末：2026-09-25（中秋）照樣拿當天當請求日期，摩根 PCF 的估值日
    （下一交易日 09-29）被夾回 09-25 寫進 DB，DB 最新日變成假日，產生一份內容等於 09-24
    的假報表；連假中的週末班次（退回週五 09-25）與 09-28（教師節）也一樣。
    這裡把各 daily_update_* 的 scraper 換成只記錄請求日期的替身、把 main 的時鐘固定在
    連假各天，確認每個來源拿到的請求日期都是 09-24。
    """
    from datetime import date, datetime, timedelta
    from loguru import logger
    import main as app

    print("--- 交易日曆：休市日、補假、無交易僅結算日；開始／最後交易日有開盤 ---")
    try:
        from src.trading_calendar import TWSE_CLOSED_WEEKDAYS, is_trading_day, last_trading_day
    except ImportError as e:
        check("交易日曆模組存在（src/trading_calendar.py）", False, str(e)[:80])
    else:
        closed = ["2026-01-01", "2026-02-12", "2026-02-13", "2026-02-16", "2026-02-20", "2026-07-10",
                  "2026-09-25", "2026-09-28", "2026-10-09", "2026-10-23", "2026-10-26", "2026-12-25"]
        opened = ["2026-01-02", "2026-02-11", "2026-02-23", "2026-09-24", "2026-09-29"]
        wrong_closed = [d for d in closed if is_trading_day(date.fromisoformat(d))]
        wrong_open = [d for d in opened if not is_trading_day(date.fromisoformat(d))]
        check("休市日（含補假、無交易僅結算日）不是交易日", not wrong_closed, f"誤判為交易日：{wrong_closed}")
        check("開始交易日、最後交易日與一般平日是交易日", not wrong_open, f"誤判為休市：{wrong_open}")
        check("週末不是交易日", not is_trading_day(date(2026, 9, 26)) and not is_trading_day(date(2026, 9, 27)))
        bad_entries = [d for year, days in TWSE_CLOSED_WEEKDAYS.items() for d in days
                       if date.fromisoformat(d).weekday() >= 5 or date.fromisoformat(d).year != year]
        check("休市清單只列平日、且放在正確年份", not bad_entries, f"有問題的列：{bad_entries}")
        backs = {d: last_trading_day(date(2026, 9, d)).isoformat() for d in (24, 25, 26, 27, 28, 29)}
        check("連假各天退回 09-24，09-29 維持當天",
              backs == {24: "2026-09-24", 25: "2026-09-24", 26: "2026-09-24", 27: "2026-09-24",
                        28: "2026-09-24", 29: "2026-09-29"}, f"{backs}")
        typhoon_backs = {d: last_trading_day(date(2026, 10, d)).isoformat() for d in (22, 23, 24, 25, 26, 27)}
        check("10-23 颱風假接 10-26 補假：四天皆退回 10-22，10-27 維持當天",
              typhoon_backs == {22: "2026-10-22", 23: "2026-10-22", 24: "2026-10-22", 25: "2026-10-22",
                                26: "2026-10-22", 27: "2026-10-27"}, f"{typhoon_backs}")
        # 清單每年自動補（trading-calendar.yml），所以挑一個遠未來、不會被收錄的年份
        june = date(max(TWSE_CLOSED_WEEKDAYS) + 50, 6, 1)
        monday = june + timedelta(days=-june.weekday() % 7)
        check("清單未涵蓋的年份只排除週末",
              is_trading_day(monday) and not is_trading_day(monday + timedelta(days=5)))

    def frozen_clock(*when):
        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(*when)
        return Frozen

    requested = []

    def recording_scraper(returns_tuple):
        class Recorder:
            def __init__(self, *args, **kwargs):
                pass

            def get_all_mappings(self):
                return {"00TEST": "1"}

            def get_etf_holdings(self, etf_code, date_str, *args, **kwargs):
                requested.append(date_str)
                return ([], date_str) if returns_tuple else []  # 第一金回 (持股, 實際日期)
        return Recorder

    sources = ["EZMoney", "Nomura", "Capital", "FHTrust", "CTBC", "FSITC", "TSIT", "Allianz",
               "Cathay", "Morgan", "Fubon", "ABFunds", "MegaFunds", "KGI", "SinoPac"]
    patched = [f"{s}Scraper" for s in sources] + [
        "datetime", "DB_FULL_PATH", "ReportManager", "update_etf_market_data"]
    saved = {name: getattr(app, name) for name in patched}
    work = Path(tempfile.mkdtemp())
    logger.disable("main")
    logger.disable("src")
    try:
        print("--- main.py 各來源的請求日期（連假 09-25 ~ 09-28）---")
        for s in sources:
            setattr(app, f"{s}Scraper", recording_scraper(s == "FSITC"))
        app.DB_FULL_PATH = work / "requests.db"
        updaters = sorted(n for n in dir(app) if n.startswith("daily_update_"))
        cases = [((2026, 9, 25, 10, 25), "2026-09-24", "09-25 中秋主班次"),
                 ((2026, 9, 26, 10, 25), "2026-09-24", "09-26 週六（週五是假日）"),
                 ((2026, 9, 28, 10, 25), "2026-09-24", "09-28 教師節"),
                 ((2026, 9, 29, 10, 25), "2026-09-29", "09-29 一般交易日")]
        for when, expected, label in cases:
            app.datetime = frozen_clock(*when)
            requested.clear()
            for name in updaters:
                getattr(app, name)(generate_report=False)
            got = sorted(set(requested))
            check(f"{label}：{len(updaters)} 個來源的請求日期都是 {expected}",
                  len(requested) == len(updaters) and got == [expected],
                  f"{len(requested)} 次請求，日期 {got}")

        print("--- 合併報表日期：DB 已有假日的列時要夾回最近一個交易日 ---")
        db = Database(str(work / "report.db"))
        db.insert_etf_list([{"etf_code": "00401A", "etf_name": "摩根", "issuer": "Morgan"}])
        db.insert_holdings(rows_sd("00401A", "2026-09-24", DAY1))
        db.insert_holdings(rows_sd("00401A", "2026-09-25", DAY1))  # 09-25 中秋寫進去的假資料
        report_dates = []

        class RecordingReportManager:
            def __init__(self, *args, **kwargs):
                self.analyzer = self

            def detect_changes_batch(self, etf_codes, date_str):
                report_dates.append(date_str)
                return {}

            def generate_all_reports(self, changes, date_str, **kwargs):
                pass

        app.DB_FULL_PATH = work / "report.db"
        app.ReportManager = RecordingReportManager
        app.update_etf_market_data = lambda db=None: None
        app.datetime = frozen_clock(2026, 9, 26, 10, 25)
        app.generate_consolidated_reports()
        check("09-26 週六：報表日期夾回 09-24，不用假日 09-25",
              report_dates == ["2026-09-24"], f"報表日期 {report_dates}")
    finally:
        for name, value in saved.items():
            setattr(app, name, value)
        logger.enable("main")
        logger.enable("src")


def check_calendar_updater():
    """
    scripts/update_trading_calendar.py：證交所清單的篩選規則，以及寫回 src/trading_calendar.py。

    trading-calendar.yml 每週跑它，證交所公布下一年後自動開 PR；這裡不連網，用 2026 年的
    實際列驗證篩選（開始／最後交易日有開盤、週末不列、無交易僅結算日算休市）與寫回。
    """
    import importlib.util

    path = Path(__file__).parent / "scripts" / "update_trading_calendar.py"
    spec = importlib.util.spec_from_file_location("update_trading_calendar", path)
    updater = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updater)

    rows = [
        ["2026-01-01", "中華民國開國紀念日", "依規定放假1日。"],
        ["2026-01-02", "國曆新年開始交易日", "國曆新年開始交易。"],
        ["2026-02-11", "農曆春節前最後交易日", "農曆春節前最後交易。"],
        ["2026-02-12", "市場無交易，僅辦理結算交割作業", ""],
        ["2026-02-15", "農曆除夕及春節", "2月15日適逢星期日，於2月20日（星期五）補假。"],
        ["2026-02-16", "農曆除夕及春節", ""],
    ]
    closed = updater.closed_weekdays(rows)
    check("篩選：只留休市的平日（排除開始／最後交易日與週末）",
          sorted(closed) == ["2026-01-01", "2026-02-12", "2026-02-16"], f"{sorted(closed)}")

    text = updater.CALENDAR.read_bytes().decode("utf-8")
    new_text = updater.insert_years(text, [updater.render_year(2099, {"2099-01-01": "測試"})])
    namespace = {}
    exec(compile(new_text, "trading_calendar_rewritten", "exec"), namespace)
    days = namespace["TWSE_CLOSED_WEEKDAYS"]
    check("寫回：新年份接在最後、原有年份不變",
          days.get(2099) == frozenset({"2099-01-01"}) and days.get(2026) == updater.load_closed_weekdays()[2026],
          f"years={sorted(days)}")


def check_stale_source_alert():
    """
    scripts/check_stale_sources.py：每日班次最後一步，有 ETF 連續多個交易日沒有新資料就讓班次失敗。

    2026-11 中信、聯博、兆豐各停更 2～5 週，期間每個班次都是 success。這裡用同樣的形狀重現：
    一檔停在 11-03、一檔停在 10-22，其他照常，確認會被點名；固定落後一天的來源、當天漏一次的來源、
    週末與休市日都不可誤報。
    """
    import contextlib
    import importlib.util
    import io
    from datetime import date

    path = Path(__file__).parent / "scripts" / "check_stale_sources.py"
    spec = importlib.util.spec_from_file_location("check_stale_sources", path)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)

    today = date(2026, 11, 26)
    # 代號要以 A 結尾（主動式 ETF），checker 與守衛一樣只看 etf_list 裡 LIKE '%A' 的列
    latest = {"00901A": "2026-11-26",   # 當日已有
              "00902A": "2026-11-25",   # 固定落後一天的來源
              "00903A": "2026-11-24",   # 當天漏一次
              "00904A": "2026-11-03",   # 中信的形狀：11-04 起停更
              "00905A": "2026-10-22"}   # 兆豐的形狀：10-27 起停更（10-23 颱風假、10-26 補假不算）
    db, db_path = fresh_db()
    db.insert_etf_list([{"etf_code": code, "etf_name": code, "issuer": ""} for code in list(latest) + ["00906A"]])
    for code, day in latest.items():
        db.insert_holdings(rows_sd(code, day, DAY1))

    behind = {code: checker.trading_days_behind(day, today) for code, day in latest.items()}
    check("落後交易日數：當日 0、落後一天 1、漏一次 2、11-03 之後 17、10-22 之後 23（休市日不算）",
          behind == {"00901A": 0, "00902A": 1, "00903A": 2, "00904A": 17, "00905A": 23}, f"{behind}")
    check("週末執行以週五為準，不多算",
          checker.trading_days_behind("2026-11-27", date(2026, 11, 29)) == 0
          and checker.trading_days_behind("2026-11-26", date(2026, 11, 29)) == 1)

    stale = checker.find_stale(db_path, today, 3)
    check("停更清單：沒有任何持股的排最前，其餘依落後天數；正常落後與漏一次的不列",
          stale == [("00906A", None, None), ("00905A", "2026-10-22", 23), ("00904A", "2026-11-03", 17)],
          f"{stale}")

    def run_quiet(path_, ignore):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = checker.run(path_, today, 3, ignore)
        return code, buffer.getvalue().splitlines()

    code, lines = run_quiet(db_path, set())
    check("有停更的 ETF -> 回傳 1（班次失敗），每檔一行 ::error::",
          code == 1 and sum(1 for line in lines if line.startswith("::error::")) == 3, f"code={code}")
    code, lines = run_quiet(db_path, {"00904A", "00905A", "00906A"})
    check("停更的 ETF 全列在 STALE_IGNORE -> 回傳 0，但仍印成 ::warning::",
          code == 0 and sum(1 for line in lines if line.startswith("::warning::")) == 3, f"code={code}")
    code, lines = run_quiet(db_path, {"00905A"})
    check("只忽略其中一檔 -> 其餘照樣讓班次失敗", code == 1, f"code={code}")

    db2, db2_path = fresh_db()
    db2.insert_etf_list([{"etf_code": code_, "etf_name": code_, "issuer": ""} for code_ in ("00901A", "00902A")])
    db2.insert_holdings(rows_sd("00901A", "2026-11-26", DAY1))
    db2.insert_holdings(rows_sd("00902A", "2026-11-25", DAY1))
    code, lines = run_quiet(db2_path, set())
    check("全部正常（含固定落後一天的來源）-> 回傳 0", code == 0, f"code={code}")


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

    print("=== 第二批來源日期解析（台新/安聯/群益/摩根）===")
    check_batch2_parsers()

    print("=== 第三批來源日期解析（兆豐/凱基/永豐）===")
    check_batch3_parsers()

    print("=== 第四批來源日期解析（野村/復華）===")
    check_batch4_parsers()

    print("=== 2026-11 靜默停更的來源（聯博版面／第一金彙總列／中信網域）===")
    check_stalled_source_fixes()

    print("=== 海外成分股（00988A）：代號慣例／解析／名稱／單位 ===")
    check_foreign_holdings()

    print("=== 統一 00981A：Excel 版面位移／API 資料日期 ===")
    check_ezmoney_layout_and_pcf_date()

    print("=== UPSERT：created_at＝首次寫入時間 ===")
    check_upsert_created_at()

    print("=== 報表層：落後的 ETF 不可從任一半消失 ===")
    check_report_layer()

    print("=== 報表層：沒有新資料的 ETF 不重列變動，改標「今日沒有新資料」 ===")
    check_stale_etfs_not_repeated()

    print("=== 每日持股報表：單日、跨期、缺基準及零異動 ===")
    check_report_comparison_periods()

    print("=== 重生已發布的報表：只有指定的 ETF 用新資料，其他固定在發布當時的資料日期 ===")
    check_pinned_regeneration()

    print("=== 本機回補兆豐：歷史查詢日期、只補缺的交易日、補完重生報表 ===")
    check_megafunds_local_backfill()

    print("=== 國定假日：請求日期與報表日期退回最近一個交易日 ===")
    check_holiday_dates()

    print("=== 交易日曆自動更新：證交所清單篩選與寫回 ===")
    check_calendar_updater()

    print("=== 來源停更警報：連續多個交易日沒有新資料要讓班次失敗 ===")
    check_stale_source_alert()

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
