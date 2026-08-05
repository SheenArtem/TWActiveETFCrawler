# 新增 ETF 與 ETF 名稱指南

**什麼時候讀：** 新增一檔 ETF、或要改 ETF 的中文名稱。

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

若該投信還沒有 scraper，要新寫一支，先讀 `data-sources.md` 的優先順序與踩雷筆記。

## 怎麼確認還缺哪些 ETF

用 TWSE OpenData `STOCK_DAY_ALL`（`https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL`）
撈出所有 `00xxxA` 代號，再與 `etf_list` 比對。兩個坑：

- `exchangeReport/ETF_NAV` 那支端點目前回傳 HTML 錯誤頁而非 JSON，不能用。
- **不能用名稱關鍵字判斷是不是海外型。** 00981A 主動統一台股增**長**、00991A 主動復華**未來50**、
  00992A 主動群益科技**創新** 都是純台股，卻會被「增長／未來50／創新」誤判
  （00409A 復華**全球**未來50 才是海外）。要逐檔看基金全名。

## ETF 名稱

- 唯一來源是 `src/etf_names.py`，`main.py` 各家 `daily_update_*` 都呼叫 `get_etf_name(etf_code)`。
  不要在 `main.py` 內寫死名稱或用 `f'XXX ETF {etf_code}'` 這種佔位字串。
- `Database.insert_etf_list()` 是 `INSERT OR REPLACE`，所以改了對照表後，
  **下次爬蟲執行就會自動覆蓋 DB 裡的舊名稱**，不需要手動改 `data/etf_holdings.db`
  （該檔有進 git，手動改會產生 binary diff 且容易與 origin 衝突）。
- 已產生的歷史報表（`docs/report_*.html`、`docs/data_*.json`、`reports/*.md`）沿用當時的名稱，
  不會自動更新；要讓歷史報表一致，跑 `scripts/regenerate_reports.py`。
