# GitHub Pages 設定指南

## 📊 報告系統說明

本系統現在會自動生成三種格式的報告：

1. **TXT 格式** (`reports/changes_YYYY-MM-DD.txt`) - 純文字報告，向後兼容
2. **Markdown 格式** (`reports/changes_YYYY-MM-DD.md`) - 簡潔列表式，適合 GitHub 閱讀
3. **HTML 格式** (`docs/report_YYYY-MM-DD.html`) - 互動式圖表儀表板，用於 GitHub Pages

## 🚀 啟用 GitHub Pages

### 步驟 1：推送代碼到 GitHub

```bash
git add .
git commit -m "Add report generation system with Markdown and HTML formats"
git push origin main
```

### 步驟 2：啟用 GitHub Pages

1. 前往您的 GitHub 倉庫
2. 點擊 **Settings** (設定)
3. 在左側選單找到 **Pages**
4. 在 **Source** 下拉選單中選擇：
   - **Branch**: `main`
   - **Folder**: `/docs`
5. 點擊 **Save** (儲存)

### 步驟 3：等待部署

- GitHub 會自動部署您的網站
- 通常需要 1-2 分鐘
- 部署完成後，您會看到網址：`https://yourusername.github.io/TWActiveETFCrawler/`

## 📁 檔案結構

```
TWActiveETFCrawler/
├── reports/                    # 報告目錄
│   ├── changes_2026-01-27.txt # 純文字報告
│   └── changes_2026-01-27.md  # Markdown 報告
├── docs/                       # GitHub Pages 目錄
│   ├── index.html             # 主頁面（報告列表）
│   ├── report_2026-01-27.html # 每日報告頁面
│   ├── data_2026-01-27.json   # 報告資料（JSON）
│   └── reports_index.json     # 報告索引
└── src/
    ├── holdings_analyzer.py   # 分析器（含 Markdown 生成）
    ├── report_generator.py    # HTML 報告生成器
    └── report_manager.py      # 報告管理器
```

## 🎨 報告格式說明

### Markdown 報告（提案 A）

- ✅ 簡潔的表格式呈現
- ✅ 使用 `<details>` 折疊區塊
- ✅ Emoji 標示增減方向（📈📉）
- ✅ 適合在 GitHub 上直接閱讀

**範例**：查看 `reports/changes_2026-01-27.md`

### HTML 報告（提案 B）

- ✅ 互動式圖表（Chart.js）
- ✅ 圓餅圖顯示變動分布
- ✅ 長條圖顯示熱門調整股票
- ✅ 響應式設計（手機友善）
- ✅ Dark Mode 支援

**範例**：開啟 `docs/report_2026-01-27.html` 或訪問 GitHub Pages

## 🔄 自動更新流程

每次執行 `python main.py --all` 時：

1. 系統抓取最新的 ETF 持股資料
2. 偵測持股變動
3. 自動生成三種格式的報告：
   - TXT → `reports/`
   - Markdown → `reports/`
   - HTML + JSON → `docs/`
4. 更新報告索引 (`docs/reports_index.json`)
5. 推送到 GitHub 後，GitHub Pages 自動更新

## 📱 網頁功能

### 主頁面 (`index.html`)

- 📊 統計資訊卡片
- 📋 歷史報告列表
- 🌙 深色模式切換
- 📱 響應式設計

### 報告頁面 (`report_YYYY-MM-DD.html`)

- 📈 變動分布圓餅圖
- 🔥 熱門調整股票 TOP 10
- 📋 詳細變動明細表
- 🎨 漸層背景設計

## 🛠️ 自訂設定

### 修改網頁標題

編輯 `docs/index.html`：

```html
<title>您的標題</title>
<h1>📊 您的標題</h1>
```

### 修改 GitHub 連結

編輯 `docs/index.html` 底部：

```html
<a href="https://github.com/yourusername/TWActiveETFCrawler" target="_blank">GitHub</a>
```

### 修改報告保留天數

編輯 `src/report_manager.py`：

```python
# 只保留最近 90 天的記錄
reports = reports[:90]  # 改成您想要的天數
```

## 📝 使用範例

### 查看最新報告

1. **Markdown 格式**：
   ```bash
   cat reports/changes_2026-01-27.md
   ```

2. **網頁格式**：
   訪問 `https://yourusername.github.io/TWActiveETFCrawler/`

### 下載報告資料

```bash
# 下載 JSON 格式
curl https://yourusername.github.io/TWActiveETFCrawler/data_2026-01-27.json
```

## 🔧 故障排除

### 問題：GitHub Pages 沒有更新

**解決方案**：
1. 確認 `docs/` 目錄已推送到 GitHub
2. 檢查 GitHub Actions 是否有錯誤
3. 等待 1-2 分鐘讓 GitHub 重新部署

### 問題：圖表沒有顯示

**解決方案**：
1. 檢查瀏覽器控制台是否有錯誤
2. 確認 `data_YYYY-MM-DD.json` 檔案存在
3. 檢查 JSON 格式是否正確

### 問題：中文顯示亂碼

**解決方案**：
- 所有 HTML 檔案都已設定 `<meta charset="UTF-8">`
- 確保檔案以 UTF-8 編碼儲存

## 📊 效能優化

- 報告索引只保留最近 90 天
- 圖表使用 CDN 載入（Chart.js）
- 響應式圖片和佈局
- 最小化 HTTP 請求

## 🎯 下一步

1. ✅ 設定 GitHub Actions 自動執行爬蟲
2. ✅ 添加 RSS Feed 支援
3. ✅ 實作報告比較功能
4. ✅ 添加電子郵件通知

## 📧 聯絡資訊

如有問題，請開 Issue 或 Pull Request！

---

**享受您的 ETF 追蹤系統！** 📊✨
