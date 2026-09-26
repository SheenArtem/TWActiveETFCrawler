# Handoff（TWActiveETFCrawler）

最後更新：2026-09-26。完整歷史與證據在 `.ai/archive/handoff-2026-09-26.md`；
設計理由在 `.ai/guides/`（`date-alignment.md`、`data-sources.md`、`adding-an-etf.md`）。

## 目前目標與狀態

**（E）國定假日產生假報表日——已修正上線、連假缺的資料已回補，待真實班次驗證。**

- 程式（`f0c8590`）：新增 `src/trading_calendar.py`（證交所 2026 平日休市日）；main.py 各來源的
  請求日期與合併報表的日期上限改用 `last_trading_day()`，週末與國定假日都退回最近一個交易日。
  測試 `check_holiday_dates()`（`test_duplicate_guard.py`）：舊程式 5 項紅、修正後全綠（CI）。
- 資料（`337b592`）：刪 00401A 09-25（與 09-24 逐列相同）與 09-25 報表、索引條目（補回被擠出的
  05-19）；補第一金 00408A／00994A 的 09-24、兆豐 00996A 的 09-21 ~ 09-24（本機抓）；
  09-21 ~ 09-24 報表只替這幾檔重生。09-24 現為 22/23 檔，只缺 00988A（來源還沒發布）。

**（D）00981A 資料日期整串晚一個交易日——已修正、回補、上線（`01c860b`），待 09-29 生產驗證。**
Excel 依表頭找股票表、API 備援改用 `TranDate`；機制寫在 `date-alignment.md`「整串平移」。
其他 22 檔以收盤價稽核 07-02 ~ 09-24：沒有任何一組配到前一日或後一日，07-30／07-31 有 15 組分不出。
細節在封存檔。

**（C）00988A 主動統一全球創新（2026-09-03 加入）**：每日都有寫入；`etf_list` 為 23、守衛分母 23。

**（A）（B）**：三檔補齊、日期錯位第二批皆已結案，細節在封存檔。

## 下一步

1. **連假班次驗證（09-26 ~ 09-28，修正後第一批）**：log 各來源請求日期應為 2026-09-24、
   合併報表日期 09-24；DB 與 `docs/` 不應出現 09-25／09-26／09-28。
2. **09-29 18:25 主班次驗證**：
   - 00981A：log 出現 `Excel date confirmed` 或 `Excel actual date`、沒有 `falling back to API`，寫入 09-29。
   - 00988A：寫入資料日期 09-24（在適用日 09-30 那份裡）。
   - 00408A／00994A 會再拿到 09-24（UPSERT，不增列）；00996A 預期仍 403（第 3 項）。
3. **00996A 兆豐 403**：只擋 GitHub runner（本機 GET／POST 都 200），推測是封鎖 runner IP。
   09-21 ~ 09-24 已從本機補齊，09-29 起每個交易日會再缺；長期解法未定。
   回補：POST `qdt`＝適用日（`data-sources.md` 兆豐列）。
4. **每年補交易日曆**：`src/trading_calendar.py` 只有 2026，2026-12-31 前要補 2027
   （證交所 OpenAPI `holidaySchedule` 公布後）；颱風休市不在清單內，當天要手動補，否則又會產生假報表。
5. **首頁「各 ETF 近 5 日買賣明細」沒有去重**（`docs/index.html` 的 `loadPerETFData()`）：
   停更或假日時同一次變動在每個報表日重複出現、合計重複計入；另外兩個面板已依
   （ETF, 資料日期）去重。未處理。
6. **上櫃的主動式 ETF 沒被盤點到**：櫃買 09-24 行情有 00411A 主動統一前沿科技、00998A 主動復華
   金融股息，`adding-an-etf.md` 的盤點只查上市（TWSE `STOCK_DAY_ALL`）。要不要收錄待使用者決定。
7. 00988A：首頁卡片與個股反查（輸入 `SNDK US`）是否顯示「千股」，找時間在瀏覽器確認。
8. 待決定：00412A 安聯亞洲半導體（海外型，尚未掛牌）要不要收錄。
9. 觀察（非錯誤）：第一金 00408A／00994A 的權重合計長期在 101–117%，是來源本身的算法。

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
- **重生歷史報表要固定其他 ETF 的 `data_date`**（做法見 `date-alignment.md`「整串平移」）；
  `scripts/regenerate_reports.py` 會整份重生、不更新 `reports_index.json`、HTML 帶當下時間，只適合全面回填。
- 07-30 以前的 `docs/data_*.json` 沒有 `market` 欄位（前端從代號判斷單位，不需回填）。
- 驗證層級：（E）有 red-before／green-after（CI）、DB 與報表對修改前逐組比對；尚缺真實班次
  （09-26 起）。（D）尚缺 09-29 走修好的 Excel 路徑。（A）～（E）各批都**沒有獨立審查**
  （使用者 2026-08-09 決定不做；內建 code review 只在要求時跑，且屬自我審查）。
- 收盤價稽核、連假回補與重生的腳本都沒有進 repo（做法寫在 `date-alignment.md`）；上櫃歷史行情要用
  `tpex.org.tw/www/zh-tw/afterTrading/otc?date=YYYY/MM/DD&type=EW`，舊的 `stk_quote_result.php`
  不理會日期、永遠回最新一天。
- 已知取捨見 `date-alignment.md`「已知取捨與殘留風險」。
