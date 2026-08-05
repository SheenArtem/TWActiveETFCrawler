# TWActiveETFCrawler 專案規則

## 資料來源原則（最重要）

**優先順序：投信官網的「下載檔案」＞ 解析網頁 DOM ＞ 投信 API。**

1. **首選：官網可下載的檔案。** 找 PCF（申購買回清單）、持股明細的 Excel／CSV 下載點，抓檔案下來直接解析。
   PCF 是法規必須每日揭露的資料，檔案格式與網址規則通常最穩定。
2. **次選：解析網頁 DOM。** 官網沒有檔案下載時，用 Playwright 開頁面、等資料渲染完成後解析表格。
   一併抓取網頁上顯示的「資料日期」，不要用請求日期當成資料日期。
3. **最後才考慮 API。** 投信自家的 JSON API 過去多次出問題：欄位改名、日期語意不一致
   （回傳次一交易日或舊資料）、無預警改版、需要 token 或特殊標頭。除非前兩條路都走不通，
   否則不要用；真的用了，要在 scraper 檔案開頭註明原因與已知風險。

**理由：** 這個專案踩過的雷幾乎都來自 API 的日期語意——摩根 PCF 的估值日是次一交易日，
第一金 API 的 `sdate` 與請求日不同，都造成過網頁顯示未來日期或資料錯位。
檔案下載的來源通常自帶明確的資料日期，錯位風險最低。

**日期規則：** 一律以資料來源自己標示的日期為準（檔名、檔案內欄位、網頁上的「資料日期」），
不要用執行當天的日期填充。合併進報表時，夾住不晚於今日。

## 各投信目前的取得方式

| 投信 | 模組 | 方式 | 備註 |
| --- | --- | --- | --- |
| 中信 CTBC | `src/ctbc_scraper.py` | 網頁下載 Excel | Playwright 點「下載EXCEL」，符合首選原則 |
| 摩根 Morgan | `src/morgan_scraper.py` | 下載 PCF xlsx | 必須帶 `Referer` = 產品頁，否則 Akamai 403；估值日是次一交易日，需夾到請求日 |
| 聯博 ABFunds | `src/abfunds_scraper.py` | 下載 holdings xlsx | 需帶 `Referer`；「代碼」欄是 ISIN，台股取 `isin[5:9]` |
| 統一 EZMoney | `src/ezmoney_scraper.py` | 下載 Excel | 實際日期由 Excel 內容取得 |
| 富邦 Fubon | `src/fubon_scraper.py` | 解析網頁 DOM | 基金資產頁 SSR 直出表格，無需下載 |
| 台新 TSIT | `src/tsit_scraper.py` | 解析網頁 DOM | 表頭定位，會隨改版變動 |
| 第一金 FSITC | `src/fsitc_scraper.py` | **API（原則的已知例外）** | 見下方「已知例外」 |
| 其他 | 各自 `src/*_scraper.py` | 見各檔案開頭註解 | |

## 已知例外：第一金 FSITC 仍走 API

2026-08-05 實測結果：

- 官網**沒有**任何持股檔案可下載。「檔案下載」區只有公開說明書／月報 PDF（`ViewFile.aspx`），
  「申購買回清單」是頁面內的分頁，資料由 `WebAPI.aspx/Get_hd` 等 API 動態渲染，沒有匯出按鈕。
- 網頁 DOM 上顯示的「資料日期」是**查詢輸入框的值（今天）**，不是資料實際日期。
  實測當天網頁顯示 2026-08-05，但資料實際是 2026-08-04。
- API 回傳的 `sdate` 才是真正的資料日期，這也是 commit `ce87043` 修掉日期錯位所依據的欄位。

**結論：** 改成解析網頁 DOM 會失去唯一可靠的資料日期來源，讓已修好的日期錯位 bug 回歸，
因此第一金維持走 API。若日後官網提供檔案下載或在 DOM 明確標示資料日期，應優先改回原則路徑。

## 新增 ETF 的流程

1. 先確認是**純台股**主動式 ETF（海外股票型、債券型不在範圍）。
2. 若該投信已有 scraper，只要在對應的代碼對照表加一筆：
   - `CTBC_ETF_CODES`（中信，值是 ETF 頁網址 `/Etf/<fund_id>/Combination` 中的數字）
   - `FSITCScraper.FUND_ID_MAP`（第一金，值是官網 `FundDetail.aspx?ID=<n>` 的 n）
   - 其他投信同理，見各檔案頂端常數
3. **對照表的值必須用基金全名驗證，不能靠猜或掃號。**
   例：第一金「台股趨勢優**選**」是 00994A、「台股趨勢優**股息**」是 00408A，只差一字。
4. 在 `src/etf_names.py` 的 `ETF_NAMES` 加中文名稱，值用**證交所官方簡稱**（取得方式見該檔 docstring）。
   漏加不會出錯，但網頁會顯示純代號。
5. 加完後實際跑一次，確認抓到的持股數、資料日期、權重合理，再收工。

## ETF 名稱

- 唯一來源是 `src/etf_names.py`，`main.py` 各家 `daily_update_*` 都呼叫 `get_etf_name(etf_code)`。
  不要在 `main.py` 內寫死名稱或用 `f'XXX ETF {etf_code}'` 這種佔位字串。
- `Database.insert_etf_list()` 是 `INSERT OR REPLACE`，所以改了對照表後，
  **下次爬蟲執行就會自動覆蓋 DB 裡的舊名稱**，不需要手動改 `data/etf_holdings.db`
  （該檔有進 git，手動改會產生 binary diff 且容易與 origin 衝突）。
- 已產生的歷史報表（`docs/report_*.html`、`docs/data_*.json`、`reports/*.md`）沿用當時的名稱，
  不會自動更新；要讓歷史報表一致，跑 `scripts/regenerate_reports.py`。

## 環境與慣例

- Windows + PowerShell。debug 時中文字串不要寫在 `python -c` 裡（CP950 會壞），寫成 `.py` 檔再執行。
- 抓取實際跑在 GitHub Actions；查 DB 前先 `git pull`，本地資料庫常落後 origin。
- 成分股中文簡稱以代號為主鍵統一，對照表在 `data/stock_names.json`，
  唯一插入點是 `Database.get_holdings_by_date()`。
