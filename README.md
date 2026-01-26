# 台灣主動式 ETF 持股追蹤系統

[![Daily ETF Scraper](https://github.com/SheenArtem/TWActiveETFCrawler/actions/workflows/daily-scraper.yml/badge.svg)](https://github.com/SheenArtem/TWActiveETFCrawler/actions/workflows/daily-scraper.yml)

自動追蹤台灣主動式 ETF 的每日持股變化，直接從各家投信官網抓取數據，使用 SQLite 本地資料庫儲存，並透過 GitHub Actions 實現雲端自動化執行。

## ✨ 功能特色

- ✅ **多家投信支援**：EZMoney、野村、群益、復華、中信、第一金、台新、安聯
- ✅ **每日自動抓取**：GitHub Actions 每天早上 6:00 自動執行
- ✅ **變動追蹤**：自動偵測並報告成分股變動（新增/移除/持股變化）
- ✅ **持股單位顯示**：以台灣習慣的「張」為單位（1張 = 1000股）
- ✅ **SQLite 資料庫**：查詢快速，資料完整保存
- ✅ **防封鎖機制**：隨機延遲、User-Agent 輪換
- ✅ **自動清理**：保留 365 天資料，資料庫大小可控
- ✅ **完整日誌**：詳細記錄執行狀況和錯誤

## 📊 支援的投信 ETF

| 投信 | ETF 代碼 | ETF 名稱 |
|------|----------|----------|
| EZMoney | 00981A | 主動統一台股增長 |
| 野村投信 | 00980A | 野村台灣創新科技50 |
| 群益投信 | 00982A | 群益台股高息成長 |
| 復華投信 | 00984A, 00985A | 復華台灣科技優息、復華台股基礎建設 |
| 中信投信 | 00991A | 中信臺灣智慧50 |
| 第一金投信 | - | （現有ETF） |
| 台新投信 | 00987A | 台新台灣永續優選 |
| 安聯投信 | 00995A | 安聯台灣科技趨勢 |

## 🚀 快速開始

### 1. Clone 專案

```bash
git clone https://github.com/SheenArtem/TWActiveETFCrawler.git
cd TWActiveETFCrawler
```

### 2. 安裝依賴

```bash
pip install -r requirements.txt
playwright install chromium  # 部分投信需要
```

### 3. 執行更新

```bash
# 更新所有投信 ETF
python main.py --all

# 只更新特定投信
python main.py --ezmoney
python main.py --nomura
python main.py --ctbc

# 查看資料庫統計
python main.py --stats
```

## 📈 成分股變動追蹤

系統會自動分析並報告每日的成分股變動：

```
============================================================
=== 2026-01-27 ETF成分股變動報告 ===
============================================================

【00981A - 主動統一台股增長】
  新增成分股 (1):
    └─ 2330 台積電 (權重: 8.50%, 持股: 50.00張)
  
  權重與持股變動 (2):
    ├─ 2412 中華電
    │  權重: 2.50% → 4.80% (▲2.30%)
    │  持股: 80.00張 → 150.00張 (▲70.00張)
    │
    └─ 2882 國泰金
       權重: 3.10% → 2.30% (▼0.80%)
       持股: 200.00張 → 150.00張 (▼50.00張)

總計：處理 1 個ETF，發現 3 筆變動
============================================================
```

### 配置變動追蹤

在 `.env` 檔案中調整設定：

```bash
# 變動追蹤設定
ENABLE_CHANGE_TRACKING=True        # 啟用/停用變動追蹤
WEIGHT_CHANGE_THRESHOLD=0.5        # 權重變動閾值（%）
SAVE_CHANGE_REPORTS=True           # 是否儲存報告檔案
REPORTS_DIR=reports                # 報告儲存目錄
```

**變動偵測規則：**
- 任何股數變化（即使只有 1 股）都會被偵測
- 權重變化 >= 0.5% 會特別標註
- 報告會同時顯示權重和持股（張數）的變化

## 🤖 GitHub Actions 自動化

系統已配置每天早上 6:00（台北時間）自動執行。

### 設定步驟

1. **Fork 或 Push 到 GitHub**

2. **啟用 GitHub Actions**
   - 進入專案 Settings → Actions → General
   - 選擇 "Read and write permissions"
   - 勾選 "Allow GitHub Actions to create and approve pull requests"
   - 點擊 Save

3. **手動測試**
   - 進入 Actions 標籤
   - 選擇 "Daily ETF Scraper"
   - 點擊 "Run workflow"

## 📁 專案結構

```
TWActiveETFCrawler/
├── .github/workflows/
│   └── daily-scraper.yml       # GitHub Actions 工作流程
├── src/
│   ├── config.py               # 配置管理
│   ├── database.py             # 資料庫管理
│   ├── holdings_analyzer.py    # 變動分析模組（新）
│   ├── ezmoney_scraper.py      # EZMoney 爬蟲
│   ├── nomura_scraper.py       # 野村投信爬蟲
│   ├── capital_scraper.py      # 群益投信爬蟲
│   ├── fhtrust_scraper.py      # 復華投信爬蟲
│   ├── ctbc_scraper.py         # 中信投信爬蟲
│   ├── fsitc_scraper.py        # 第一金投信爬蟲
│   ├── tsit_scraper.py         # 台新投信爬蟲
│   ├── allianz_scraper.py      # 安聯投信爬蟲
│   └── utils.py                # 工具函數
├── data/
│   └── etf_holdings.db         # SQLite 資料庫
├── logs/                       # 日誌檔案
├── reports/                    # 變動報告（新）
├── main.py                     # 主程式
├── requirements.txt
└── README.md
```

## 💾 資料庫結構

### ETF 清單表 (etf_list)

| 欄位 | 類型 | 說明 |
|------|------|------|
| etf_code | TEXT | ETF 代碼（主鍵）|
| etf_name | TEXT | ETF 名稱 |
| issuer | TEXT | 發行投信 |
| listing_date | TEXT | 上市日期 |
| last_updated | TEXT | 最後更新時間 |

### 持股明細表 (holdings)

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | INTEGER | 自動編號（主鍵）|
| etf_code | TEXT | ETF 代碼 |
| stock_code | TEXT | 股票代碼 |
| stock_name | TEXT | 股票名稱 |
| shares | INTEGER | 持股數量（股）|
| market_value | REAL | 市值 |
| weight | REAL | 權重（%）|
| date | TEXT | 日期 (YYYY-MM-DD) |
| created_at | TEXT | 建立時間 |

## 📖 使用範例

### Python 查詢

```python
from src.database import Database
from src.config import DB_FULL_PATH

db = Database(DB_FULL_PATH)

# 查詢最新持股
holdings = db.get_holdings_by_date('2026-01-26', '00981A')
for h in holdings[:5]:
    lots = round(h['shares'] / 1000, 2)
    print(f"{h['stock_code']} {h['stock_name']}: {h['weight']:.2f}%, {lots:.2f}張")
```

### 匯出為 CSV

```python
import pandas as pd
from src.database import Database
from src.config import DB_FULL_PATH

db = Database(DB_FULL_PATH)
holdings = db.get_holdings_by_date('2026-01-26', '00981A')

df = pd.DataFrame(holdings)
df['張數'] = (df['shares'] / 1000).round(2)
df.to_csv('00981A_holdings.csv', index=False, encoding='utf-8-sig')
```

### 分析變動

```python
from src.holdings_analyzer import HoldingsAnalyzer
from src.database import Database
from src.config import DB_FULL_PATH

db = Database(DB_FULL_PATH)
analyzer = HoldingsAnalyzer(db)

# 偵測今天的變動
changes_dict = analyzer.detect_all_changes('2026-01-27')
if changes_dict:
    report = analyzer.generate_report(changes_dict, '2026-01-27')
    print(report)
```

## ⚙️ 配置說明

在 `.env` 檔案中可配置：

```bash
# 資料庫設定
DB_PATH=data/etf_holdings.db
DATA_RETENTION_DAYS=365

# 爬蟲設定
REQUEST_DELAY_MIN=1.0
REQUEST_DELAY_MAX=3.0
MAX_RETRIES=3

# 日誌設定
LOG_LEVEL=INFO
LOG_PATH=logs/etf_crawler.log

# 變動追蹤設定
ENABLE_CHANGE_TRACKING=True
WEIGHT_CHANGE_THRESHOLD=0.5
SAVE_CHANGE_REPORTS=True
REPORTS_DIR=reports
```

## 🔧 添加新的 ETF

### 1. 確認投信類型

查看該 ETF 是由哪家投信發行，找到對應的 scraper 檔案。

### 2. 編輯對應的 scraper

例如要添加 EZMoney 的新 ETF：

```python
# 編輯 src/ezmoney_scraper.py
EZMONEY_ETF_CODES = {
    '00981A': '49YTW',  # 現有
    '00XXX': 'XXXXX',   # 新增（需找出 fundCode）
}
```

### 3. 執行測試

```bash
python main.py --ezmoney
```

## 📋 執行時間說明

- **GitHub Actions**：每天台北時間早上 06:00 執行
- **資料更新時間**：
  - EZMoney ETF：當日下午 18:00 後更新（當日資料）
  - 其他投信 ETF：通常 T+1 更新（前一交易日資料）

## ❓ 常見問題

### Q: 為什麼沒有變動報告？

A: 如果兩天之間沒有任何成分股變動（新增/移除/股數變化），系統會顯示「無變動」。

### Q: 資料從哪裡來？

A: 直接從各家投信官網抓取公開的持股資料，更即時、更準確。

### Q: 資料庫會不會太大？

A: 採用滾動保留 365 天策略，資料庫維持在 50-60 MB，完全在 GitHub 限制內。

### Q: 可以在本地執行嗎？

A: 可以！執行 `python main.py --all` 即可手動更新所有 ETF。

## ⚠️ 注意事項

- 本專案僅供學習研究使用
- 請遵守各投信網站使用規範
- 不保證資料完整性和正確性
- 投資決策請以官方資料為準

## 📄 授權

MIT License

## 🤝 貢獻

歡迎提交 Issue 或 Pull Request！

## 👤 作者

[SheenArtem](https://github.com/SheenArtem)

---

⭐ 如果這個專案對您有幫助，歡迎給個星星！
