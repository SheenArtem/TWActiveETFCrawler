# 資料來源指南

**什麼時候讀：** 改任何 scraper、新增投信來源、或懷疑某家投信的資料日期不對。

## 為什麼是「下載檔案 ＞ DOM ＞ API」

1. **首選：官網可下載的檔案。** 找 PCF（申購買回清單）、持股明細的 Excel／CSV 下載點，抓檔案下來直接解析。
   PCF 是法規必須每日揭露的資料，檔案格式與網址規則通常最穩定，而且檔案本身自帶明確的資料日期。
2. **次選：解析網頁 DOM。** 官網沒有檔案下載時，用 Playwright 開頁面、等資料渲染完成後解析表格。
   一併抓取網頁上顯示的「資料日期」，不要用請求日期當成資料日期。
3. **最後才考慮 API。** 投信自家的 JSON API 過去多次出問題：欄位改名、日期語意不一致
   （回傳次一交易日或舊資料）、無預警改版、需要 token 或特殊標頭。除非前兩條路都走不通，
   否則不要用；真的用了，要在 scraper 檔案開頭註明原因與已知風險。

**理由：** 這個專案踩過的雷幾乎都來自 API 的日期語意——摩根 PCF 的估值日是次一交易日，
第一金 API 的 `sdate` 與請求日不同，都造成過網頁顯示未來日期或資料錯位。

## 各投信目前的取得方式

「防護」欄 = 是否受寫入層日期錯位防護攔截（見 `date-alignment.md`）；
跳過的那幾家由 scraper 標 `source_dated=True`。

| 投信 | 模組 | 方式 | 資料日期來源 | 防護 | 備註 |
| --- | --- | --- | --- | --- | --- |
| 中信 CTBC | `src/ctbc_scraper.py` | 網頁下載 Excel | ✅ Excel 內「資料日期」欄 | 跳過 | Playwright 點「下載EXCEL」；當日資料下午才更新 |
| 摩根 Morgan | `src/morgan_scraper.py` | 下載 PCF xlsx | ✅ 估值日（領先一日＝新檔的判準） | 條件式：新檔跳過、舊檔防護 | VD>請求日＝當日新檔，夾回請求日後標 source_dated；VD=請求日＝舊檔維持防護。必須帶 `Referer` = 產品頁，否則 Akamai 403 |
| 聯博 ABFunds | `src/abfunds_scraper.py` | 下載 holdings xlsx | ✅ content-disposition 檔名 | 跳過 | 「代碼」欄是 ISIN，台股取 `isin[5:9]` |
| 統一 EZMoney | `src/ezmoney_scraper.py` | 下載 Excel | ✅ Excel 表頭（民國年） | 跳過（僅 Excel 路徑） | 另有一條 API 路徑仍用請求日期，維持防護 |
| 富邦 Fubon | `src/fubon_scraper.py` | 解析網頁 DOM | ✅ 頁面「資料日期」 | 跳過 | SSR 直出表格；當日資料下午才更新 |
| 第一金 FSITC | `src/fsitc_scraper.py` | **API（原則的已知例外）** | ✅ API `sdate` | 跳過 | 見下方「已知例外」 |
| 台新 TSIT | `src/tsit_scraper.py` | 解析網頁 DOM | ✅ 黏在表頭文字裡：`2026/8/5每基數實際申購總價金(元)`，以「日期＋每基數」為錨 | 跳過 | **`#PUB_DATE` 是 PCF 適用日（下一交易日），絕不可當資料日期**（2026-08-05 實測值為未來日 08-06）。頁面出現多個不同日期時視為改版、保守退回 |
| 群益 Capital | `src/capital_scraper.py` | **buyback API（原則的已記錄例外）** | ✅ API `data.pcf.date2`＝持股基準日 | 跳過（API 路徑） | Excel 與頁面皆無資料日期，API 是唯一日期來源（與 Excel 同資料）；`date1` 是下一交易日的 PCF 適用日，勿用。API 失敗退回 Playwright+Excel 備援，備援不帶 source_dated、防護生效 |
| 安聯 Allianz | `src/allianz_scraper.py` | 解析網頁 DOM | ✅ 頁面標「資料日期 : YYYY/MM/DD」 | 跳過 | 同富邦模式。歷史錯位最大戶（19 組，已刪除並重生報表） |
| 野村 Nomura | `src/nomura_scraper.py` | API | ✅ 結構安全（2026-08-05 實測）：API 嚴格遵守 `SearchDate`，未發布日回空、可查歷史、回應回帶資料日期 | 仍防護 | 用請求日期但**不會錯位**（要嘛拿到該日資料、要嘛空）。可選擇性標 source_dated 消滅同內容日誤擋 |
| 復華 FHTrust | `src/fhtrust_scraper.py` | API 下載 Excel | ✅ 結構安全（2026-08-05 實測）：URL 帶日期且嚴格遵守，未發布日回 JSON 錯誤而非假 Excel | 仍防護 | 同野村，不會錯位 |
| 國泰 Cathay | `src/cathay_scraper.py` | API | ❌ **無法取得** | 仍防護 | 見下方「國泰 API 無法信任日期」 |
| 兆豐 Mega | `src/megafunds_scraper.py` | 解析網頁 DOM（WebForms postback） | ✅ 黏在金額欄位文字前：`2026/08/07 每基數實際申購總價金(元)`，以「日期＋每基數」為錨（同台新樣態） | 跳過 | 換基金要帶 `__VIEWSTATE` postback（`fund_id=23`＝00996A），**只能回送頁面實際有的 hidden**；頁面最顯眼的「查詢日期」是 PCF 適用日（下一營業日），絕不可用 |
| 凱基 KGI | `src/kgi_scraper.py` | 解析網頁 DOM（partial view） | ✅ `(2026/08/07)每受益權單位淨資產價值` 括號內即基準日 | 跳過 | 持股表由 `/Fund/RedemptionVC` 回 HTML 片段（`fundID=J024`＝00407A）；hidden `#DataDate` 是適用日，絕不可用 |
| 永豐 SinoPac | `src/sinopac_scraper.py` | 解析網頁 DOM（SSR） | ✅ 頁面標「資料日期：YYYY/MM/DD」 | 跳過 | 官網**有** xlsx 下載卻不採用，見下方「已知例外：永豐的下載檔案拿不到最新」；`qdate`／`hDate` 是適用日，絕不可用；頁面同時輸出桌機版與手機版表格，只能取桌機版 |

## 已知例外：第一金 FSITC 仍走 API

2026-08-05 實測結果：

- 官網**沒有**任何持股檔案可下載。「檔案下載」區只有公開說明書／月報 PDF（`ViewFile.aspx`），
  「申購買回清單」是頁面內的分頁，資料由 `WebAPI.aspx/Get_hd` 等 API 動態渲染，沒有匯出按鈕。
- 網頁 DOM 上顯示的「資料日期」是**查詢輸入框的值（今天）**，不是資料實際日期。
  實測當天網頁顯示 2026-08-05，但資料實際是 2026-08-04。
- API 回傳的 `sdate` 才是真正的資料日期，這也是 commit `ce87043` 修掉日期錯位所依據的欄位。

**結論：** 改成解析網頁 DOM 會失去唯一可靠的資料日期來源，讓已修好的日期錯位 bug 回歸，
因此第一金維持走 API。若日後官網提供檔案下載或在 DOM 明確標示資料日期，應優先改回原則路徑。

## 已知例外：永豐的下載檔案拿不到最新，因此走 DOM

2026-08-09 實測。永豐 PCF 頁面的「資料下載」是表單送 `op=2`，確實回 xlsx
（`Content-Disposition: attachment; filename=Pcf-00410A-20260807.xlsx`），但它**只接受
早於今天的日期**：

| 送出的 `hDate` | 結果 |
| --- | --- |
| 2026-08-10（預設值，未來日） | 回 136 bytes 空白頁，沒有檔案 |
| 2026-08-07 | 回 xlsx，內文標「資料日期：2026/08/06」 |
| 2026-08-06 | 回 xlsx，內文標「資料日期：2026/08/05」 |

前端也內建同樣限制（`downloadPcf()` 在 `qdate >= today` 時直接 alert）。因為 `hDate` 是
**適用日**、內容基準日又比它早一個交易日，走檔案路徑每天只能拿到「前一交易日的前一交易日」，
永遠落後。網頁 SSR 沒有這個限制（預設就顯示最新一份），而且頁面自己標了「資料日期」，
與檔案內文逐字相同——日期可靠度一樣，資料新鮮度卻差一天，所以這裡走 DOM。

**檔名裡的日期是適用日，不是資料日期**（`Pcf-00410A-20260807.xlsx` 內文是 08/06），
日後若改走檔案，不可用檔名當資料日期。

## 三家新來源共通的「前瞻日」樣態

兆豐、凱基、永豐（2026-08-09 新增）的申購買回清單頁面，最顯眼的日期一律是
**PCF 適用日（下一營業日）**，不是持股基準日——與摩根 PCF 的估值日、群益的 `date1`
同款。三家各自的正確錨點見上表。這是本專案第 4～6 個同款案例，可以直接當成預設假設：
**投信 PCF 頁面上那個「日期」欄位，先當它是適用日，除非頁面明確寫「資料日期」。**

**錨點不能跨投信照抄。** 台新與兆豐的「日期＋每基數」前面是基準日，但永豐頁面的排列
剛好相反——實測可見文字是 `（證劵代碼：00410A）2026/08/10 每申購基數之預收申購總價金(元)`，
那個日期是**適用日**。同一種文字樣態在不同投信代表不同語意，每家都要各自實測驗證。

## 國泰 API 無法信任日期

2026-08-05 實測：`GetETFDetailStockList?FundCode=EA&SearchDate=<date>`

- 傳 `2026-08-05`（當日資料尚未產出）→ 回傳與 `2026-08-04` **完全相同**的 52 筆，不做任何提示
- 傳 `2026-08-06`（未來日）→ `success=false`、`returnMessage=查無資料`

也就是說它對「已過去但當日資料未產出」的日期會**靜默回退到前一日**，而回應中沒有任何日期欄位
可以識破。因此國泰無法改用來源日期，只能靠寫入層防護攔截。

## 寫新 scraper 的踩雷筆記

- 投信網站幾乎都是 Angular／AEM SPA，HTML 沒持股資料；要嘛找 XHR JSON API、要嘛找下載 xlsx。
- 摩根 PCF 沒帶 `Referer` 會被 Akamai 擋 403。
- 國泰把 API 全暴露在 `cwapi.cathaysite.com.tw/api/ETF/*`，可從 `main.<hash>.js` 中 grep `"api/ETF/`。
- 聯博（AllianceBernstein，`abfunds_scraper.py`）與安聯（Allianz，`allianz_scraper.py`）是不同公司，別搞混。
- ASP.NET WebForms 的 postback（兆豐）**只能回送頁面上實際存在的 hidden 欄位**。
  多送 `__EVENTTARGET`／`__EVENTARGUMENT`（該頁沒有這兩個）會讓請求被丟回首頁，
  拿到一個沒有持股表、卻是 HTTP 200 的頁面。切換基金後要驗證頁面標題的股票代號
  真的是目標 ETF，否則會把別檔的持股寫進這一檔。
- 手機版重複表格（永豐）：同一份持股會同時以桌機版一大表與手機版每檔一小表輸出，
  盲抓 `find_all('table')` 會重複計算。用「第一列前兩格是不是真表頭」來區分。
