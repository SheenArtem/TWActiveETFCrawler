# 新增 ETF 與 ETF 名稱指南

**什麼時候讀：** 新增一檔 ETF、或要改 ETF 的中文名稱。

## 新增 ETF 的流程

1. 先確認是**純台股**主動式 ETF（海外股票型、債券型原則上不在範圍）。
   目前唯一的例外是 00988A 主動統一全球創新（2026-09-03 使用者決定收錄），約四分之三權重
   是海外股票。要再收錄含海外成分股的 ETF，先讀下方「含海外成分股的 ETF」。
2. 若該投信已有 scraper，只要在對應的代碼對照表加一筆：
   - `CTBC_ETF_CODES`（中信，值是 ETF 頁網址 `/Etf/<fund_id>/Combination` 中的數字）
   - `FSITCScraper.FUND_ID_MAP`（第一金，值是官網 `FundDetail.aspx?ID=<n>` 的 n）
   - `MEGA_ETF_CODES`（兆豐，值是 `trade_pcf.aspx` 上 `fund_id` 下拉選單的 value）
   - `KGI_ETF_CODES`（凱基，值是官網內部 fundID，見清單頁 `AllFundName` hidden 欄位）
   - `SINOPAC_ETF_CODES`（永豐，值就是 ETF 代號，直接組進 PCF 頁網址最後一段）
   - 其他投信同理，見各檔案頂端常數
3. **對照表的值必須用基金全名驗證，不能靠猜或掃號。**
   例：第一金「台股趨勢優**選**」是 00994A、「台股趨勢優**股息**」是 00408A，只差一字。
4. 在 `src/etf_names.py` 的 `ETF_NAMES` 加中文名稱，值用**證交所官方簡稱**（取得方式見該檔 docstring）。
   漏加不會出錯，但網頁會顯示純代號。
5. 加完後實際跑一次，確認抓到的持股數、資料日期、權重合理，再收工。

若該投信還沒有 scraper，要新寫一支，先讀 `data-sources.md` 的優先順序與踩雷筆記。

## 怎麼確認還缺哪些 ETF

**最新盤點（2026-09-03 重查 TWSE `STOCK_DAY_ALL`）：上市 `00xxxA` 共 30 檔（比 08-09 多了
00409A 主動復華全球50，海外型）。22 檔純台股全部已追蹤、缺口為零；8 檔海外股票型
（00402A／00409A／00983A／00986A／00988A／00989A／00990A／00997A）中只收錄 00988A，
其餘 7 檔不追蹤。** 純台股最後補上的是 00996A（兆豐）／00407A（凱基）／00410A（永豐）。

用 TWSE OpenData `STOCK_DAY_ALL`（`https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL`）
撈出所有 `00xxxA` 代號，再與 `etf_list` 比對。兩個坑：

- `exchangeReport/ETF_NAV` 那支端點目前回傳 HTML 錯誤頁而非 JSON，不能用。
- **不能用名稱關鍵字判斷是不是海外型。** 00981A 主動統一台股增**長**、00991A 主動復華**未來50**、
  00992A 主動群益科技**創新** 都是純台股，卻會被「增長／未來50／創新」誤判
  （00409A 復華**全球**未來50 才是海外）。要逐檔看基金全名。

## 含海外成分股的 ETF（目前只有 00988A）

- 代號慣例：台股純數字；海外**照抄來源的 Bloomberg 代號「代號 市場」**（`SNDK US`、`6981 JP`、
  `009150 KS`、`3308 HK`、`300408 CH`、`IFX GY`），空格與市場後綴都要留。
  判定（`market_of()`）與單位（`lot_unit()`）在 `src/stock_markets.py`。
- **絕不能把後綴去掉只留數字。** 2026-09-03 實測 00988A 的 39 檔海外持股中有 5 檔數字部分等於
  真實台股代號（6997 JP↔博弘、3308 HK↔聯德、6871 JP↔新鑫、5801 JP↔建弘投信、4180 JP↔安成藥），
  去掉後綴就會被 `canonical_name()` 改名成台股，並在跨 ETF 統計裡與台股加總。
- scraper 的列篩選不能寫「只收 4 位數字」——那會把海外持股整批靜默丟掉（00988A 會少 39/48 檔、
  約四分之三權重）。用 `market_of()`：回 `None` 才是該跳過的表頭／合計列。
- 報表單位：台股「張」、海外「千股」（兩者都是股數/1000，只差名稱）；`docs/data_*.json` 的
  持股與變動每列帶 `market`（`TW` 或市場後綴），前端也用同一條規則判斷單位。
- 資料日期：00988A 的 Excel 表頭「資料日期」比 PCF 適用日早兩個交易日（09/03 上午下載到的是
  115/09/01；API 的 `TranDate` 同為 09/01、`PostDate` 為 09/03）。這是來源的節奏，
  照常以來源日期寫入，報表會逐檔回退。
- 要再收錄另一檔含海外成分股的 ETF：先用該投信的原始檔案確認海外代號格式是否也是
  Bloomberg「代號 市場」；不是的話要先擴充 `stock_markets.py`，並補
  `test_duplicate_guard.py` 的 `check_foreign_holdings()`。

## ETF 名稱

- 唯一來源是 `src/etf_names.py`，`main.py` 各家 `daily_update_*` 都呼叫 `get_etf_name(etf_code)`。
  不要在 `main.py` 內寫死名稱或用 `f'XXX ETF {etf_code}'` 這種佔位字串。
- `Database.insert_etf_list()` 是 `INSERT OR REPLACE`，所以改了對照表後，
  **下次爬蟲執行就會自動覆蓋 DB 裡的舊名稱**，不需要手動改 `data/etf_holdings.db`
  （該檔有進 git，手動改會產生 binary diff 且容易與 origin 衝突）。
- 已產生的歷史報表（`docs/report_*.html`、`docs/data_*.json`、`reports/*.md`）沿用當時的名稱，
  不會自動更新；要讓歷史報表一致，跑 `scripts/regenerate_reports.py`。
