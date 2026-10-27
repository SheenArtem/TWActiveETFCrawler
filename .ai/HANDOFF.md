# Handoff（TWActiveETFCrawler）

最後更新：2026-10-27。完整歷史與證據在 `.ai/archive/handoff-2026-09-26.md`；
設計理由在 `.ai/guides/`（`date-alignment.md`、`data-sources.md`、`adding-an-etf.md`）。

## 目前目標與狀態

**（F）全 15 家投信日期標註稽核與摩根／野村／復華來源日期強化（2026-10-27）——已實作並上線，22/23 檔採用來源日期。**

- 盤點全 15 家（23 檔）後，把最後三家「上游其實有明確基準日、但程式原本沒讀或用前瞻日推算」的 scraper 全部收斂：
  1. **摩根 00401A（`src/morgan_scraper.py`）**：PCF xlsx 表頭（`Record Type='H'`）除了前瞻的 `Valuation Date`（次一交易日）外，
     本身就帶 `NAV Date`（實際持股／淨值基準日，`YYYYMMDD`）。改為優先直接採用 `NAV Date` 並標 `source_dated=True`
     （`Valuation Date` 夾回邏輯退為 `NAV Date` 缺漏時的備援），從根源消除臨時颱風假把舊檔夾成假日寫入 DB 的問題。
  2. **野村 00980A／00985A／00999A（`src/nomura_scraper.py`）**：解析 `GetFundAssets` 回應的 `FundAsset.NavDate` 與股票表
     `table['NavDate']`（`YYYY/MM/DD`）並標 `source_dated=True`（缺漏或兩處矛盾時退回請求日、維持防護）。
  3. **復華 00991A（`src/fhtrust_scraper.py`）**：`download_portfolio_excel` 新增 `PK` 檔頭檢查（非交易日／未發布回 12 bytes
     `'查無資料'` 時回傳 `None`，不再寫壞 `.xlsx`）；`parse_excel_file` 讀取表頭 `日期: YYYY/MM/DD` 並標 `source_dated=True`，
     股票表依 `證券代號` 動態定位並改用 `market_of()` 篩選代號。
- 現況：**22/23 檔（14 家投信）**直接採用來源日期並標 `source_dated=True`；僅剩**國泰 00400A（1/23）**因 API 無任何日期欄位且未發布時會靜默回傳前一日，繼續依賴 `Database._reject_duplicate_snapshots()`。

**（E）國定假日與颱風假防護——國定假日（09-28、10-09、10-26）生產驗證全過；10-23 颱風假已補日曆並清理假報表。**

- 國定假日（`f0c8590`）：`src/trading_calendar.py` 上線後，09-28（教師節）、10-09（國慶補假）、10-26（光復節補假）
  真實班次皆未產生假資料或假報表；09-29 與 10-12 開盤班次皆正常銜接落後來源（第一金、00988A）。
- 2026-10-23（五）颱風休市：未即時補入 `TWSE_CLOSED_WEEKDAYS`，導致 10-23 ~ 10-26 八個班次退回 `2026-10-23`，
  寫入 00401A `10-23`（56 列，與 `10-22` 逐列相同；收盤價檢驗全 22 檔 `10-22` 皆配中真 `10-22`，無任何 ETF
  把 `10-22` 資料只存在 `10-23` 底下）並產出 `10-23` 假報表。2026-10-27 已補 `"2026-10-23"` 進日曆與測試、
  刪 00401A `10-23` 與周五提前寫入的第一金 00408A／00994A `10-22`（55＋43 列，交由當晚 `10-27` 班次自然抓回，
  避免吃掉 `10-20 → 10-21` 變動）、移除 `10-23` 報表並從索引補回被擠出的 `06-12`。
- 00996A 兆豐本機回補：補齊 `09-29 ~ 10-22` 共 17 個交易日（896 列），並只替 00996A 重生這 17 份歷史報表
  （其餘 22 檔固定發布時 `data_date`、逐項核對無變動、保留原 `update_time` 與 MD 時間戳）。
  全 ETF 缺口檢查 `08-01 ~ 10-22` 為 0。

**（D）00981A 資料日期整串晚一個交易日——已於 09-29 起生產驗證通過，結案。**
Excel 依表頭找股票表、API 備援改用 `TranDate`；09-29 ~ 10-22 每日皆正常寫入當日持股（收盤價稽核吻合）。

**（C）00988A 主動統一全球創新（2026-09-03 加入）**：每日都有寫入；`etf_list` 為 23、守衛分母 23。

**（A）（B）**：三檔補齊、日期錯位第二批皆已結案，細節在封存檔。

## 下一步

1. **10-27 18:25 主班次驗證**：
   - 00408A／00994A 查 `10-27` 寫入 `10-22`，00988A 寫入 `10-22`（適用日 `10-28` 那份），`10-27` 報表帶出變動。
   - 00996A 預期仍 403（下一項）。
2. **00996A 兆豐 403——原因已確認：兆豐前端的 Akamai 依來源 IP 擋 GitHub runner（Azure），與程式、標頭無關。**
   runner 上 requests／curl／真 Chromium 一律 403、連 `robots.txt` 也被擋，開發機同類 client 全 200（證據與判別方法見
   `data-sources.md`「兆豐：GitHub runner 被 Akamai 依來源 IP 擋」）。未分辨只擋雲端 IP 還是擋所有非台灣 IP。
   `09-21 ~ 10-22` 已從本機補齊，`10-27` 起每個交易日會再缺；長期解法未定（要台灣出口 IP，或附 Akamai
   `Reference #` 請兆豐放行）。回補：POST `qdt`＝適用日（`data-sources.md` 兆豐列）。
3. **每年補交易日曆**：`src/trading_calendar.py` 只有 2026，2027 尚未公布。
   `trading-calendar.yml` 每週一檢查，公布後自動開 PR；**2026-12-31 前要合併**，否則 2027 的國定假日
   又會產生假報表。自動開 PR 這條路徑要等證交所公布才會第一次真正跑到。颱風休市不在清單內，當天要手動補。
4. **首頁跨報表彙總（原第 5、10 項，PR #1）——已上線並在瀏覽器核對，結案。** 各 ETF 近 5 日買賣明細依
   （ETF, 資料日期）去重、每日欄位歸屬到資料日期；同步買賣超 `modified` 的每日欄位改為累加（CI 有
   red-before／green-after：`check_homepage_per_etf_dedup()`、`check_homepage_cross_etf_per_day()`）。
   2026-09-26 用線上資料照首頁邏輯獨立重算，與 Chromium 畫出的 22 張卡片＋
   20 個同步名次共 3438 格全數一致；落後來源畫在資料日期欄、最舊一欄累加兩次變動（00408A 2542 的
   9/18＝+300＋180）。核對時發現的 09-23 缺口已修（見（E））。
5. **上櫃的主動式 ETF 沒被盤點到**：櫃買 09-24 行情有 00411A 主動統一前沿科技、00998A 主動復華
   金融股息，`adding-an-etf.md` 的盤點只查上市（TWSE `STOCK_DAY_ALL`）。要不要收錄待使用者決定。
6. **00988A 的「千股」顯示——已在瀏覽器確認，結案。** 2026-09-26 線上首頁：00988A 卡片 13 列海外股帶
   「· 千股」、7 列台股不帶，摘要合計標千股；個股反查 `SNDK US`（含小寫、多餘空白）顯示「持股（千股）」
   「單位：千股」，數字與資料檔獨立重算一致；對照 2330 顯示「張」。
7. 待決定：00412A 安聯亞洲半導體（海外型，尚未掛牌）要不要收錄。
8. 觀察（非錯誤）：第一金 00408A／00994A 的權重合計長期在 101–117%，是來源本身的算法。

## 限制與驗證邊界

- **測試只在 GitHub Actions 跑**（`tests.yml`，分支用 `gh workflow run tests.yml --ref <branch>`），
  不在開發機跑；本機只做資料作業（抓來源、寫 DB、重生報表）。2026-09-26 由使用者決定。
- **DB 是 binary、bot 每天 commit**：主班次 Cloudflare 觸發 `workflow_dispatch`（台北 18:25／10:25Z），
  後備 `schedule` 近期（10-23 ~ 10-26）落在 16:33–19:10Z。資料修正要基於最新 `origin/main` 並在
  兩班之間 push；push 前若 bot 已 commit，要在新的 DB 上重做資料作業。
- **單家補抓不可用 `main.py --<來源>` 裸跑**（會以只含該家變動的字典覆蓋整份日報）：
  改用 `daily_update_<來源>(generate_report=False)` 只寫 DB，再 `generate_consolidated_reports()`。
- 請求日期來源的錯位搶救（封存檔「08-05 錯位資料搶救」）：先刪錯位群組再重跑（不刪會留孤兒列），
  重跑必須在事故當日的 UTC 日內。
- **重生歷史報表要固定其他 ETF 的 `data_date`**（做法見 `date-alignment.md`「整串平移」）；
  `scripts/regenerate_reports.py` 會整份重生、不更新 `reports_index.json`、HTML 帶當下時間，只適合全面回填。
- 07-30 以前的 `docs/data_*.json` 沒有 `market` 欄位（前端從代號判斷單位，不需回填）。
- 驗證層級：（E）有 red-before／green-after（CI）、DB 與報表對修改前逐組比對、09-26／09-28／10-09／10-26 真實班次；
  （D）09-29 起真實班次走修好的 Excel 路徑已確認。（A）～（E）各批都**沒有獨立審查**
  （使用者 2026-08-09 決定不做；內建 code review 只在要求時跑，且屬自我審查）。
- 收盤價稽核、連假回補與重生的腳本都沒有進 repo（做法寫在 `date-alignment.md`）；上櫃歷史行情要用
  `tpex.org.tw/www/zh-tw/afterTrading/otc?date=YYYY/MM/DD&type=EW`，舊的 `stk_quote_result.php`
  不理會日期、永遠回最新一天。
- 已知取捨見 `date-alignment.md`「已知取捨與殘留風險」。
