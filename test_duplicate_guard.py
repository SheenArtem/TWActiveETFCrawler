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

    print("--- 摩根：估值日領先＝新檔，未領先＝舊檔 ---")
    # 摩根的規則不獨立成函式（在 get_etf_holdings 內），此處驗證其依據的
    # _parse_valuation_date 與「領先才可信」的比較語意
    from src.morgan_scraper import MorganScraper
    vd = MorganScraper._parse_valuation_date("20260806")
    check("摩根：VD 解析為 ISO 格式", vd == "2026-08-06")
    check("摩根：VD 領先請求日 -> 新檔（source_dated 應為 True）", vd > "2026-08-05")
    check("摩根：VD 未領先 -> 舊檔（source_dated 應為 False）", not (vd > "2026-08-06"))
    check("摩根：VD 解析不到 -> 空字串（走 fallback）",
          MorganScraper._parse_valuation_date(None) == "")


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
    from src.holdings_analyzer import HoldingChange
    from src.report_generator import HTMLReportGenerator
    from src.report_manager import ReportManager

    db_f, _ = fresh_db()
    db_f.insert_holdings(rows_sd("00988A", "2026-09-01", [("2330", 550000, 2.58), ("SNDK US", 13000, 1.22)]))
    mgr = ReportManager(db_f, Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()))
    built = mgr.build_etf_holdings({"00988A": "主動統一全球創新"}, "2026-09-01")
    markets = {h["stock_code"]: h["market"] for h in built[0]["holdings"]} if built else {}
    check("持股總覽每列帶 market（TW／US）", markets == {"2330": "TW", "SNDK US": "US"}, f"{markets}")

    gen = HTMLReportGenerator(Path(tempfile.mkdtemp()))
    holdings_html = gen._generate_etf_holdings_html(built)
    check("持股總覽 HTML：台股列「張」、海外列「千股」、卡片標示含海外成分股",
          "550張" in holdings_html and "13千股" in holdings_html and "13張" not in holdings_html
          and "含 1 檔海外成分股" in holdings_html)

    changes = {"00988A": [
        HoldingChange(change_type="ADDED", stock_code="SNDK US", stock_name="SANDISK CORP",
                      new_shares=13000, new_lots=13.0),
        HoldingChange(change_type="SHARES_UP", stock_code="2330", stock_name="台積電",
                      old_shares=500000, new_shares=550000, shares_diff=50000,
                      old_lots=500.0, new_lots=550.0, lots_diff=50.0),
    ]}
    dash = gen.generate_dashboard_data(changes, "2026-09-01", {"00988A": "主動統一全球創新"}, built)
    entry = dash["detailed_changes"][0]
    check("變動明細 JSON 帶 market（新增 US／變動 TW）",
          entry["added"][0]["market"] == "US" and entry["modified"][0]["market"] == "TW")
    details_html = gen._generate_details_html(dash["detailed_changes"])
    check("變動明細 HTML：海外新增列「千股」、台股變動列「張」",
          "13千股" in details_html and "+50張" in details_html)
    txt = mgr.analyzer.generate_report(changes, "2026-09-01")
    check("TXT 報告：海外列「千股」、台股列「張」", "13.00千股" in txt and "550.00張" in txt)
    md = mgr.analyzer.generate_markdown_report(changes, "2026-09-01")
    check("Markdown 報告：海外列「千股」、台股列「張」", "13.00千股" in md and "550張" in md)


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

    print("=== 第二批來源日期解析（台新/安聯/群益/摩根）===")
    check_batch2_parsers()

    print("=== 第三批來源日期解析（兆豐/凱基/永豐）===")
    check_batch3_parsers()

    print("=== 海外成分股（00988A）：代號慣例／解析／名稱／單位 ===")
    check_foreign_holdings()

    print("=== UPSERT：created_at＝首次寫入時間 ===")
    check_upsert_created_at()

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
