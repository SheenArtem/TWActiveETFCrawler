@echo off
REM ============================================================
REM Taiwan Active ETF Tracker - Daily Update Batch Script (Advanced)
REM 用於 Windows 排程任務的批次檔（進階版，含獨立日誌）
REM ============================================================

REM 設定工作目錄為批次檔所在目錄
cd /d %~dp0

REM 建立日誌目錄（如果不存在）
if not exist "logs\batch" mkdir "logs\batch"

REM 設定日誌檔案名稱（含日期時間）
set LOG_FILE=logs\batch\batch_%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%.log
set LOG_FILE=%LOG_FILE: =0%

REM 開始記錄（同時輸出到螢幕和檔案）
call :log "============================================================"
call :log "Taiwan Active ETF Tracker - Daily Update"
call :log "Start Time: %date% %time%"
call :log "============================================================"
call :log ""

REM 檢查 Python 是否可用
python --version >nul 2>&1
if %errorlevel% neq 0 (
    call :log "ERROR: Python not found in system PATH!"
    call :log "Please install Python or add it to system PATH."
    exit /b 1
)

call :log "Python found, starting ETF data update..."
call :log ""

REM 執行 Python 程式
python main.py --all >> "%LOG_FILE%" 2>&1

REM 檢查執行結果
set EXIT_CODE=%errorlevel%

call :log ""
if %EXIT_CODE% equ 0 (
    call :log "============================================================"
    call :log "Update completed successfully!"
    call :log "End Time: %date% %time%"
    call :log "============================================================"
) else (
    call :log "============================================================"
    call :log "ERROR: Update failed with error code %EXIT_CODE%"
    call :log "End Time: %date% %time%"
    call :log "Please check logs at:"
    call :log "  - Application log: logs\etf_crawler.log"
    call :log "  - Batch log: %LOG_FILE%"
    call :log "============================================================"
)

REM 正常結束
exit /b %EXIT_CODE%

REM ============================================================
REM 函數：記錄訊息到螢幕和檔案
REM ============================================================
:log
echo %~1
echo %~1 >> "%LOG_FILE%"
goto :eof
