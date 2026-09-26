# Handoff（TWActiveETFCrawler）

最後更新：2026-09-26。完整歷史與證據在 `.ai/archive/handoff-2026-09-26.md`；
設計理由在 `.ai/guides/`（`date-alignment.md`、`data-sources.md`、`adding-an-etf.md`）。

## 目前目標與狀態

**（D）00981A 資料日期整串晚一個交易日——已修正並回補，待其他 ETF 稽核與生產驗證。**

- 起因：00981A 自 2026-07-31 起 Excel 股票表前多了期貨段，固定列數的解析器讀不到、每天退回
  統一 API；API 的日期參數是 PCF 適用日，回來的是前一交易日的持股，卻被標成請求日。
  結果 08-03 ~ 09-24 共 39 天都晚一天、真正的 09-24（30 檔減碼）沒抓到。
  機制與偵測方法寫在 `date-alignment.md`「防護擋不到的錯位：整串平移」。
- 程式（`src/ezmoney_scraper.py`）：Excel 依「股票代號」表頭找股票表；API 備援改取最新一份
  （`specificDate=False`）並以 `TranDate` 當資料日期、標 source_dated；`/Date(ms)/` 與 ISO
  兩種日期格式都認得。測試 `check_ezmoney_layout_and_pcf_date()`（`test_duplicate_guard.py`）。
- 資料：DB 內 00981A 由舊到新改標到 `TranDate`（07-31 ~ 09-23）並補上真正的 09-24；
  07-31 ~ 09-25 共 41 個已發布日期的報表只替 00981A 重生（其他 ETF 固定在發布時的 `data_date`）。
  回補與重生腳本不進 repo，做法寫在 `date-alignment.md`。
- 分支 `fix/ezmoney-trandate` 完成後 fast-forward 回 `main`。

**（C）00988A 主動統一全球創新（2026-09-03 加入）**：09-03 班次首次寫入（資料日期 09-02、44 筆），
之後每日都有寫入；`etf_list` 為 23、守衛分母 23。首頁「千股」顯示尚未在瀏覽器確認（見下一步）。

**（A）（B）**：三檔補齊、日期錯位第二批皆已結案，細節在封存檔。

## 下一步

1. **稽核其他 22 檔是否也有「整串平移」**：用收盤價配權重（權重 ∝ 股數 × 持股日收盤價）
   或同家另一個明確標日期的來源逐筆比對，確認每檔存的日期就是持股日。優先看用請求日期的
   來源：野村 00980A／00985A／00999A、復華 00991A、國泰 00400A。
2. **00981A 生產驗證**：下一個交易日 09-29 18:25 主班次，log 應出現 00981A
   `Excel date confirmed` 或 `Excel actual date`、不再有 `falling back to API`，寫入日期為 09-29。
3. **00996A 兆豐**：09-21 起每一班都 `Mega: Failed to open PCF page: HTTP 403`，最新資料停在
   09-18（未處理，要先查是封鎖 GitHub runner IP 還是頁面改版）。
4. **假日產生假報表日**：`main.py` 只避開週末、不認得國定假日；摩根 00401A 在 09-25（中秋）
   把估值日 09-29 夾到請求日寫入，DB 最新日變 09-25，產出一份內容等於 09-24 的報表。
   09-28（教師節）預期再發生一次。未處理。
5. **首頁「各 ETF 近 5 日買賣明細」沒有去重**（`docs/index.html` 的 `loadPerETFData()`）：
   停更或假日時同一次變動在每個報表日重複出現、合計重複計入；另外兩個面板已依
   （ETF, 資料日期）去重。未處理。
6. 00988A：首頁卡片與個股反查（輸入 `SNDK US`）是否顯示「千股」，找時間在瀏覽器確認。
7. 待決定：00412A 安聯亞洲半導體（海外型，尚未掛牌）要不要收錄。

## 限制與驗證邊界

- **測試只在 GitHub Actions 跑**（`tests.yml`，分支用 `gh workflow run tests.yml --ref <branch>`），
  不在開發機跑；本機只做資料作業（抓來源、寫 DB、重生報表）。2026-09-26 由使用者決定。
- **DB 是 binary、bot 每天 commit**：主班次 Cloudflare 觸發 `workflow_dispatch`（台北 18:25／10:25Z），
  後備 `schedule` 近期（09-18 ~ 09-25）落在 16:20–18:34Z。資料修正要基於最新 `origin/main` 並在
  兩班之間 push；push 前若 bot 已 commit，要在新的 DB 上重做資料作業。
- **單家補抓不可用 `main.py --<來源>` 裸跑**（會以只含該家變動的字典覆蓋整份日報）：
  改用 `daily_update_<來源>(generate_report=False)` 只寫 DB，再 `generate_consolidated_reports()`。
- 請求日期來源的錯位搶救（封存檔「08-05 錯位資料搶救」）：先刪錯位群組再重跑（不刪會留孤兒列），
  重跑必須在事故當日的 UTC 日內。
- **重生歷史報表要固定其他 ETF 的 `data_date`**；`scripts/regenerate_reports.py` 會整份重生、
  不更新 `reports_index.json`、HTML 帶當下時間，只適合全面回填。
- 07-30 以前的 `docs/data_*.json` 沒有 `market` 欄位（前端從代號判斷單位，不需回填）。
- 驗證層級：00981A 的修正有 red-before／green-after（CI）、回補前後逐筆比對與報表結構化比對，
  還沒有收盤價的獨立檢驗（下一步第 1 項會一併做 00981A）。（A）～（D）各批都**沒有獨立審查**
  （使用者 2026-08-09 決定不做；內建 code review 只在要求時跑，且屬自我審查）。
- 已知取捨見 `date-alignment.md`「已知取捨與殘留風險」。
