# TWActiveETFCrawler 專案規則

本檔是**路由表**：repo 層級的鐵則寫在這裡，細節放在 `.ai/guides/`。動手前先照下面的路由找到對應指南。

## 鐵則

**資料來源優先順序：投信官網的「下載檔案」＞ 解析網頁 DOM ＞ 投信 API。**
PCF（申購買回清單）是法規每日必揭露，檔案格式與網址規則最穩定。真的只能走 API 時，
要在該 scraper 檔案開頭註明原因與已知風險。目前唯一的例外是第一金，理由見指南。

**日期一律以來源自己標示的日期為準**（檔名、檔案內欄位、網頁上的「資料日期」），
不要用執行當天的日期填充；合併進報表時夾住不晚於今日。

**「資料日期」不等於「查詢日期」。** 第一金與台新頁面上最顯眼的日期是查詢輸入框的值（等於今天），
富邦與中信才是真正的「資料日期：YYYY/MM/DD」。抓錯就直接錯位。

**不要在 `main.py` 寫死 ETF 名稱**，一律用 `get_etf_name(etf_code)`。

**成分股代號：台股是純數字；海外股票照抄來源的 Bloomberg 代號「代號 市場」（含空格與市場後綴），
絕不能只留數字。** 00988A 有 5 檔日／港股的數字部分就是真實台股代號，去掉後綴會被改名成台股、
並在跨 ETF 統計裡被加總。scraper 篩選列時也不能用「4 位數字」當股票的判準。判定在 `src/stock_markets.py`。

## 什麼時候讀哪一份

| 什麼時候 | 讀這份 |
| --- | --- |
| 改任何 scraper、新增投信來源、或懷疑某家的資料日期不對 | `.ai/guides/data-sources.md` |
| 改 `Database.insert_holdings()`、scraper 日期欄位、報表日期邏輯、CI 早退守衛 | `.ai/guides/date-alignment.md` |
| 新增一檔 ETF、盤點還缺哪些 ETF、改 ETF 中文名稱 | `.ai/guides/adding-an-etf.md` |
| 處理含海外成分股的 ETF（目前只有 00988A）、改代號判定或報表單位 | `.ai/guides/adding-an-etf.md` 的「含海外成分股的 ETF」 |
| 接手進行中的工作、暫停、換手 | `.ai/HANDOFF.md` |

## 環境與慣例

- Windows + PowerShell。debug 時中文字串不要寫在 `python -c` 裡（CP950 會壞），寫成 `.py` 檔再執行。
- 抓取實際跑在 GitHub Actions；查 DB 前先 `git pull`，本地資料庫常落後 origin。
- 成分股中文簡稱以代號為主鍵統一，對照表在 `data/stock_names.json`，
  唯一插入點是 `Database.get_holdings_by_date()`。
- `docs/` 是 GitHub Pages 的產出目錄（`report_*.html`／`data_*.json`），不要把文件放進去；
  給 agent 讀的指南一律放 `.ai/guides/`。
- 行尾規則由 `.gitattributes` 決定（`*.md`、`*.py` 一律 LF），不要順手正規化不相關的檔案。

## 誰擁有什麼

| 檔案 | 擁有的內容 |
| --- | --- |
| `AGENTS.md`（本檔） | 鐵則與路由，不放細節 |
| `.ai/guides/*.md` | 各領域細節與踩雷筆記 |
| `.ai/HANDOFF.md` | 目前進行中的狀態與下一步，隨工作更新 |
| `src/etf_names.py` | ETF 中文名稱唯一來源 |
| `data/stock_names.json` | 成分股中文簡稱唯一來源 |
| `src/stock_markets.py` | 成分股代號慣例（台股／海外）、市場判定與報表單位「張／千股」 |
| `src/config.py` | 開關與門檻（含 `REJECT_DUPLICATE_OF_PREVIOUS_DAY`） |
