# Windows 排程任務設定指南

本文件說明如何在 Windows 上設定排程任務，自動執行 ETF 資料更新。

## 📁 可用的批次檔

### 1. `run_daily_update.bat`（簡易版）
- 基本功能：執行資料更新
- 輸出：顯示在命令提示字元視窗
- 適合：手動執行或簡單排程

### 2. `run_daily_update_advanced.bat`（進階版）⭐ 推薦
- 完整功能：執行資料更新 + 記錄批次執行日誌
- 輸出：同時顯示在螢幕並儲存到 `logs\batch\` 目錄
- 錯誤處理：檢查 Python 是否可用
- 適合：無人值守的自動排程

## 🕐 Windows 排程任務設定步驟

### 方法一：使用圖形介面（Task Scheduler）

1. **開啟工作排程器**
   - 按 `Win + R`，輸入 `taskschd.msc`，按 Enter

2. **建立基本工作**
   - 點選右側 `建立基本工作...`
   - 名稱：`Taiwan ETF Daily Update`
   - 描述：`每日自動更新台灣主動式 ETF 持股資料`

3. **設定觸發程序**
   - 選擇 `每天`
   - 設定開始時間：建議 **晚上 18:30**（各投信資料更新後）
   - 每隔：`1` 天

4. **設定動作**
   - 選擇 `啟動程式`
   - 程式或指令碼：
     ```
     C:\GIT\TWActiveETFCrawler\run_daily_update_advanced.bat
     ```
   - 起始於（選填）：
     ```
     C:\GIT\TWActiveETFCrawler
     ```

5. **進階設定**（點選「完成」前勾選「當按一下完成時，開啟此工作內容的對話方塊」）
   - ☑ 不論使用者登入與否均執行
   - ☑ 以最高權限執行
   - 設定：Windows 10

6. **完成**
   - 點選 `完成`

### 方法二：使用命令列（快速）

開啟 **系統管理員權限** 的 PowerShell，執行以下命令：

```powershell
# 建立每日排程任務（晚上 18:30 執行）
$action = New-ScheduledTaskAction -Execute "C:\GIT\TWActiveETFCrawler\run_daily_update_advanced.bat" -WorkingDirectory "C:\GIT\TWActiveETFCrawler"
$trigger = New-ScheduledTaskTrigger -Daily -At 18:30
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest

Register-ScheduledTask -TaskName "Taiwan ETF Daily Update" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "每日自動更新台灣主動式 ETF 持股資料"
```

## 🧪 測試排程任務

### 手動測試批次檔
直接雙擊執行 `run_daily_update_advanced.bat`，確認是否正常運作。

### 測試排程任務
1. 開啟工作排程器
2. 找到 `Taiwan ETF Daily Update`
3. 右鍵點選 `執行`
4. 檢查執行結果：
   - 應用程式日誌：`logs\etf_crawler.log`
   - 批次執行日誌：`logs\batch\batch_YYYYMMDD_HHMMSS.log`

## 📋 建議的排程時間

根據各投信資料更新時間，建議設定以下排程：

| 時間 | 說明 |
|------|------|
| **18:30** | 主要排程（推薦）- 大部分投信資料已更新 |
| 20:00 | 備用排程 - 確保所有資料都已更新 |

## 🔍 檢視執行記錄

### 應用程式日誌
```
C:\GIT\TWActiveETFCrawler\logs\etf_crawler.log
```

### 批次執行日誌（僅進階版）
```
C:\GIT\TWActiveETFCrawler\logs\batch\
```

## ⚠️ 注意事項

1. **電腦需保持開機**：排程任務只在電腦開機時執行
2. **網路連線**：確保電腦在執行時有網路連線
3. **使用者登入**：建議設定「不論使用者登入與否均執行」
4. **防火牆/防毒軟體**：確認不會阻擋 Python 或批次檔執行
5. **定期檢查**：建議每週檢查一次日誌，確認資料正常更新

## 🛠️ 疑難排解

### 問題：排程任務沒有執行
**解決方法**：
1. 檢查工作排程器中的「上次執行時間」和「上次執行結果」
2. 確認觸發程序設定正確
3. 檢查批次檔路徑是否正確

### 問題：執行失敗（錯誤代碼 1）
**解決方法**：
1. 檢查 Python 是否已正確安裝
2. 確認 Python 已加入系統 PATH
3. 手動執行批次檔測試

### 問題：資料沒有更新
**解決方法**：
1. 檢查 `logs\etf_crawler.log` 查看詳細錯誤訊息
2. 確認網路連線正常
3. 確認投信網站是否有變動（需更新爬蟲程式）

## 📞 技術支援

如有問題，請查看：
- 應用程式日誌：`logs\etf_crawler.log`
- 批次執行日誌：`logs\batch\`
- GitHub Issues：https://github.com/SheenArtem/TWActiveETFCrawler/issues
