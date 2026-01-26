# 台灣主動式 ETF 持股追蹤系統

[![Daily ETF Scraper](https://github.com/YOUR_USERNAME/TWActiveETFCrawler/actions/workflows/daily-scraper.yml/badge.svg)](https://github.com/YOUR_USERNAME/TWActiveETFCrawler/actions/workflows/daily-scraper.yml)

自動追蹤台灣主動式 ETF 的每日持股變化，直接從各家投信官網抓取數據，使用 SQLite 本地資料庫儲存，並透過 GitHub Actions 實現雲端自動化執行。

## 功能特色

- ✅ 直接從各家投信官網爬取持股資料（更準確、更即時）
- ✅ 支援多家投信：EZMoney + 野村投信
- ✅ 每日自動抓取持股明細
- ✅ SQLite 資料庫儲存，查詢快速
- ✅ GitHub Actions 雲端執行，電腦不用開機
- ✅ 自動清理 365 天前的舊資料
- ✅ 完整的防封鎖機制（隨機延遲）
- ✅ Git 版本控制，完整歷史記錄

## 目前支援的 ETF

- **00981A**: 主動統一台股增長 (EZMoney)
- **00980A**: 野村台灣創新科技50 (野村投信)

## 系統需求

- Python 3.11+
- Git

## 快速開始

### 1. Clone 專案

```bash
git clone https://github.com/YOUR_USERNAME/TWActiveETFCrawler.git
cd TWActiveETFCrawler
```

### 2. 安裝依賴

```bash
pip install -r requirements.txt
```

### 3. 每日更新

手動執行 EZMoney ETF 更新（建議於晚上 18:00 後執行）：

```bash
python main.py --ezmoney
```

手動執行野村投信 ETF 更新：

```bash
python main.py --nomura
```

### 4. 查看統計

```bash
python main.py --stats
```

## 添加新的 ETF

### 方法 1: EZMoney 網站的 ETF

編輯 `src/ezmoney_scraper.py`：

```python
EZMONEY_ETF_CODES = {
    '00981A': '49YTW',  # 主動統一台股增長
    '00000X': 'XXXXX',  # 新的 ETF（需要找出對應的 fundCode）
}
```

### 方法 2: 野村投信的 ETF

編輯 `src/nomura_scraper.py`：

```python
NOMURA_ETF_CODES = {
    '00980A': '00980A',  # 野村台灣創新科技50
    '00000X': '00000X',  # 新的 ETF
}
```

### 方法 3: 其他投信的 ETF

參考 `src/ezmoney_scraper.py` 或 `src/nomura_scraper.py`，創建新的爬蟲模組：

1. 探索該投信的網站 API
2. 創建新的 scraper 檔案（例如：`src/yuanta_scraper.py`）
3. 在 `main.py` 中添加對應的更新函數
4. 在 GitHub Actions workflow 中添加執行步驟

## GitHub Actions 自動化設定

本專案已配置 GitHub Actions，會在每天台灣時間 18:00 自動執行所有投信爬蟲並更新資料。

### 設定步驟

1. **Fork 或 Push 專案到 GitHub**

2. **啟用 GitHub Actions**
   - 進入 GitHub 專案頁面
   - 點擊 "Actions" 標籤
   - 如果提示啟用 workflow，點擊啟用

3. **設定 Git 推送權限**（重要！）
   - 進入專案 Settings → Actions → General
   - 找到 "Workflow permissions"
   - 選擇 "Read and write permissions"
   - 勾選 "Allow GitHub Actions to create and approve pull requests"
   - 點擊 Save

4. **手動觸發測試**
   - 進入 Actions 標籤
   - 選擇 "Daily ETF Scraper"
   - 點擊 "Run workflow" 測試執行

## 專案結構

```
TWActiveETFCrawler/
├── .github/
│   └── workflows/
│       └── daily-scraper.yml    # GitHub Actions 工作流程
├── src/
│   ├── __init__.py
│   ├── config.py                # 配置管理
│   ├── database.py              # 資料庫管理
│   ├── etf_scraper.py           # ETF 爬蟲核心
│   └── utils.py                 # 工具函數
├── data/
│   └── etf_holdings.db          # SQLite 資料庫（Git 追蹤）
├── logs/                        # 日誌檔案
├── .env.example                 # 環境變數範例
├── .gitignore
├── requirements.txt
├── main.py                      # 主程式進入點
└── README.md
```

## 資料庫結構

### ETF清單表 (etf_list)

| 欄位 | 類型 | 說明 |
|------|------|------|
| etf_code | TEXT | ETF 代碼（主鍵）|
| etf_name | TEXT | ETF 名稱 |
| issuer | TEXT | 發行公司 |
| listing_date | TEXT | 上市日期 |
| last_updated | TEXT | 最後更新時間 |

### 持股明細表 (holdings)

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | INTEGER | 自動編號（主鍵）|
| etf_code | TEXT | ETF 代碼 |
| stock_code | TEXT | 股票代碼 |
| stock_name | TEXT | 股票名稱 |
| shares | INTEGER | 持股數量 |
| market_value | REAL | 市值 |
| weight | REAL | 權重（%）|
| date | TEXT | 日期 (YYYY-MM-DD) |
| created_at | TEXT | 建立時間 |

## 使用範例

### Python 查詢範例

```python
import sqlite3
import pandas as pd

# 連接資料庫
conn = sqlite3.connect('data/etf_holdings.db')

# 查詢特定 ETF 的最新持股
df = pd.read_sql("""
    SELECT * FROM holdings 
    WHERE etf_code = '00940A' 
    AND date = (SELECT MAX(date) FROM holdings WHERE etf_code = '00940A')
    ORDER BY weight DESC
""", conn)

print(df)
conn.close()
```

### 匯出為 CSV

```python
import sqlite3
import pandas as pd

conn = sqlite3.connect('data/etf_holdings.db')
df = pd.read_sql("SELECT * FROM holdings WHERE date >= '2026-01-01'", conn)
df.to_csv('holdings_2026.csv', index=False, encoding='utf-8-sig')
conn.close()
```

## 資料管理策略

本系統採用**滾動保留 1 年資料**策略：

- 自動保留最近 365 天的持股資料
- 每次更新後自動清理舊資料
- 資料庫檔案大小維持在 50-60 MB
- 永不超過 GitHub 檔案大小限制

## 防封鎖機制

為避免被證交所網站封鎖，系統實作以下機制：

- ✅ 每次請求間隔 1-3 秒隨機延遲
- ✅ 每 10 筆請求後額外延遲 5-10 秒
- ✅ 隨機 User-Agent 輪換
- ✅ 指數退避重試策略（最多 3 次）
- ✅ Session 連線管理

## EZMoney ETF 整合說明

### 什麼是 EZMoney ETF？

本系統支援從 EZMoney 網站抓取特定 ETF 的每日成分股資料。目前支援：
- **00981A**: 主動統一台股增長

### 為什麼需要 EZMoney？

- 某些主動式 ETF 的資料在 EZMoney 網站上更新較快
- 提供當日最新的持股明細（下午 6 點後更新）
- 補充證交所資料來源

### 如何添加新的 EZMoney ETF？

編輯 `src/ezmoney_scraper.py`，在 `EZMONEY_ETF_CODES` 字典中添加新的對照：

```python
EZMONEY_ETF_CODES = {
    '00981A': '49YTW',  # 主動統一台股增長
    '00000X': 'XXXXX',  # 新的 ETF（需要找出對應的 fundCode）
}
```

## 野村投信 ETF 整合說明

### 什麼是野村投信 ETF？

本系統支援從野村投信網站抓取特定 ETF 的每日成分股資料。目前支援：
- **00980A**: 野村台灣創新科技50

### 如何添加新的野村投信 ETF？

編輯 `src/nomura_scraper.py`，在 `NOMURA_ETF_CODES` 字典中添加新的對照：

```python
NOMURA_ETF_CODES = {
    '00980A': '00980A',  # 野村台灣創新科技50
    '00000X': '00000X',  # 新的 ETF
}
```

### 執行時間說明

- **TWSE ETF**: 每日 18:00（資料通常 T+1 更新）
- **EZMoney ETF**: 每日 18:00 之後（當日資料在下午 6 點後才會更新）
- **野村投信 ETF**: 每日 18:00（資料通常 T+1 更新）
- **GitHub Actions**: 統一在 UTC 10:00（台北時間 18:00）執行

## 常見問題

### Q: 資料從哪裡來？

A: 資料來源為台灣證券交易所官網的公開資訊。

### Q: 多久更新一次？

A: 使用 GitHub Actions 每天台灣時間 18:00 自動更新（證交所資料通常 T+1 更新）。

### Q: 資料庫檔案會不會太大？

A: 採用滾動保留策略，資料庫維持在 50-60 MB，完全在 GitHub 限制內。

### Q: 可以在本地執行嗎？

A: 可以！執行 `python main.py --daily-update` 即可手動更新。

### Q: 如何使用 Windows 工作排程器？

A: 開啟「工作排程器」→ 建立基本工作 → 設定每日 18:00 執行 `python C:\GIT\TWActiveETFCrawler\main.py --daily-update`

## 授權

MIT License

## 注意事項

- 本專案僅供學習研究使用
- 請遵守台灣證交所網站使用規範
- 不保證資料完整性和正確性
- 投資決策請以官方資料為準

## 貢獻

歡迎提交 Issue 或 Pull Request！

## 作者

[Your Name]

---

⭐ 如果這個專案對您有幫助，歡迎給個星星！
