@echo off
REM ============================================================
REM Taiwan Active ETF Tracker - Daily Update Batch Script
REM 用於 Windows 排程任務的批次檔
REM ============================================================

REM 設定工作目錄為批次檔所在目錄
cd /d %~dp0

REM 顯示開始時間
echo ============================================================
echo Taiwan Active ETF Tracker - Daily Update
echo Start Time: %date% %time%
echo ============================================================

REM 執行 Python 程式（抓取所有投信資料）
python main.py --all

REM 檢查執行結果
if %errorlevel% equ 0 (
    echo.
    echo ============================================================
    echo Update completed successfully!
    echo End Time: %date% %time%
    echo ============================================================
) else (
    echo.
    echo ============================================================
    echo ERROR: Update failed with error code %errorlevel%
    echo End Time: %date% %time%
    echo Please check logs at: logs\etf_crawler.log
    echo ============================================================
    exit /b %errorlevel%
)

REM 正常結束
exit /b 0
