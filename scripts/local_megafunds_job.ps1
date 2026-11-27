#Requires -Version 7.0
<#
.SYNOPSIS
本機排程：從這台電腦補兆豐 00996A 的持股，重生受影響的報表，推上 main。

.DESCRIPTION
GitHub runner 被兆豐前端的 Akamai 依來源 IP 擋，每日班次抓不到 00996A；台灣的一般網路正常。
這支在「專用的 clone」裡跑，不碰開發用的工作目錄：

  等每日班次結束 -> 同步到 origin/main -> python scripts/backfill_megafunds.py -> 有變更就 commit -> push

專用 clone 與排程由 scripts/setup_local_megafunds_job.ps1 建立。紀錄寫在專用 clone 旁邊的 logs 目錄。
做法與維護方式見 .ai/guides/data-sources.md「兆豐：GitHub runner 被 Akamai 依來源 IP 擋」。

防呆：
- 只在帶有標記檔 .megafill-clone、且 origin 是 TWActiveETFCrawler 的目錄裡動作。這支會 git reset --hard，
  絕不可以對著開發用的目錄跑。
- 每日班次（Daily ETF Scraper）正在跑時先等它結束：兩邊都會改 binary 的 DB，後 push 的那一邊會失敗。
- push 被拒（中間有人先推了）就重新同步、整個重做，最多三次。
- 同一時間只跑一份；憑證過期時直接失敗，不跳出登入視窗卡住。

結束碼：0 = 補完並推上去，或沒有要補的；1 = 失敗（原因在紀錄檔最後幾行）。

.PARAMETER RepoDir
專用 clone 的位置。

.PARAMETER NoPush
只做到 commit，不 push（測試用）。
#>
param(
    [string]$RepoDir = (Join-Path $env:LOCALAPPDATA 'TWActiveETFCrawler\megafill\repo'),
    [switch]$NoPush
)

$ErrorActionPreference = 'Stop'
# python 與 git 的輸出一律當 UTF-8 讀（主控台預設是 Big5，中文會變亂碼）
try { [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false) } catch { }
$env:PYTHONUTF8 = '1'
# 憑證過期時不要跳出登入視窗：排程是隱藏視窗，會一直卡到逾時
$env:GIT_TERMINAL_PROMPT = '0'
$env:GCM_INTERACTIVE = 'never'

$logDir = Join-Path (Split-Path $RepoDir -Parent) 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$logFile = Join-Path $logDir ("megafill-{0}.log" -f (Get-Date -Format 'yyyy-MM'))

function Write-Log {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding utf8
}

function Invoke-Git {
    # 在專用 clone 裡跑 git；失敗就丟例外並帶上輸出
    $gitOutput = & git -C $RepoDir @args 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git $($args -join ' ') 失敗：$($gitOutput -join ' | ')" }
    return $gitOutput
}

function Wait-DailyScraper {
    # 每日班次正在跑（或排隊中）就等，最多等 20 分鐘。查不到（gh 沒登入、沒網路）就照常繼續，只記一筆。
    for ($i = 0; $i -lt 40; $i++) {
        $runsJson = & gh run list --repo SheenArtem/TWActiveETFCrawler --workflow daily-scraper.yml --limit 5 --json status 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $runsJson) { Write-Log '查不到每日班次的狀態（gh 無法使用），照常繼續'; return }
        $busy = @(($runsJson | ConvertFrom-Json) | Where-Object { $_.status -ne 'completed' }).Count
        if ($busy -eq 0) { return }
        if ($i -eq 0) { Write-Log '每日班次正在跑，等它結束' }
        Start-Sleep -Seconds 30
    }
    Write-Log '等了 20 分鐘每日班次還沒結束，照常繼續'
}

$mutex = [System.Threading.Mutex]::new($false, 'Local\TWActiveETFCrawler-MegaBackfill')
$exitCode = 1
$haveLock = $false
try {
    try { $haveLock = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $haveLock = $true }
    if (-not $haveLock) {
        Write-Log '另一份回補正在跑，這一次不執行'
        exit 0
    }
    Write-Log "=== 開始（RepoDir=$RepoDir）"
    if (-not (Test-Path (Join-Path $RepoDir '.megafill-clone'))) {
        throw "找不到標記檔 $RepoDir\.megafill-clone：這不是專用 clone，不執行（先跑 scripts/setup_local_megafunds_job.ps1）"
    }
    $origin = (Invoke-Git remote get-url origin | Select-Object -First 1)
    if ("$origin" -notmatch 'SheenArtem[/\\]TWActiveETFCrawler(\.git)?$') { throw "origin 不是本專案：$origin" }
    $python = if ($env:MEGAFILL_PYTHON) { $env:MEGAFILL_PYTHON } else { (Get-Command python -ErrorAction Stop).Source }
    $resultFile = Join-Path $logDir 'last-result.json'
    $pythonLog = Join-Path $logDir 'last-backfill.log'
    $messageFile = Join-Path $logDir 'last-commit-message.txt'

    $done = $false
    for ($attempt = 1; $attempt -le 3 -and -not $done; $attempt++) {
        Wait-DailyScraper
        Invoke-Git fetch --depth 1 origin main | Out-Null
        Invoke-Git reset --hard FETCH_HEAD | Out-Null
        Write-Log ("第 {0} 次：已同步到 {1}" -f $attempt, (Invoke-Git rev-parse --short HEAD | Select-Object -First 1))

        Remove-Item $resultFile, $pythonLog -ErrorAction SilentlyContinue
        Push-Location $RepoDir
        try {
            $consoleOutput = & $python -X utf8 scripts/backfill_megafunds.py --result-file $resultFile --log-file $pythonLog 2>&1
            $backfillExit = $LASTEXITCODE
        } finally { Pop-Location }
        if (Test-Path $pythonLog) {
            Get-Content $pythonLog -Encoding utf8 | ForEach-Object { Write-Log "  $_" }
        } else {
            # 連紀錄檔都沒寫出來＝python 一開始就失敗（少套件、語法錯）；把主控台輸出留下來
            $consoleOutput | ForEach-Object { Write-Log "  $_" }
        }

        Invoke-Git add data/etf_holdings.db docs reports | Out-Null
        & git -C $RepoDir diff --cached --quiet
        if ($LASTEXITCODE -eq 0) {
            if ($backfillExit -eq 0) { Write-Log '=== 完成：沒有要補的資料'; $exitCode = 0; $done = $true; break }
            throw "回補失敗（結束碼 $backfillExit），沒有任何變更"
        }

        $result = Get-Content $resultFile -Raw -Encoding utf8 | ConvertFrom-Json
        $days = @($result.inserted)
        $range = if ($days.Count -gt 1) { "$($days[0]) ~ $($days[-1])（$($days.Count) 天）" } else { "$($days[0])" }
        $body = @(
            "data: 本機回補兆豐 00996A $range",
            '',
            '由 scripts/local_megafunds_job.ps1 在開發機的排程執行（GitHub runner 被兆豐前端依來源 IP 擋）。',
            '只有 00996A 用新資料重生報表，其他 ETF 固定在發布當時的資料日期。'
        )
        if (@($result.missing).Count -gt 0) { $body += "來源查不到、沒有補的日子：$(@($result.missing) -join '、')" }
        if ($backfillExit -ne 0) { $body += "注意：回補腳本回報失敗（$($result.message)），見開發機的紀錄。" }
        Set-Content -Path $messageFile -Value $body -Encoding utf8
        Invoke-Git commit -q -F $messageFile | Out-Null
        Write-Log ("已 commit {0}：{1}" -f (Invoke-Git rev-parse --short HEAD | Select-Object -First 1), $body[0])

        if ($NoPush) { Write-Log '=== 完成：-NoPush，沒有 push'; $exitCode = 0; $done = $true; break }
        Wait-DailyScraper
        $pushOutput = & git -C $RepoDir push origin HEAD:main 2>&1
        $pushExit = $LASTEXITCODE
        $pushOutput | ForEach-Object { Write-Log "  $_" }
        if ($pushExit -eq 0) {
            $done = $true
            if ($backfillExit -ne 0) { throw "資料已推上去，但回補腳本回報失敗：$($result.message)" }
            Write-Log '=== 完成：已 push 到 main'
            $exitCode = 0
        } else {
            Write-Log 'push 沒成功（遠端有新的 commit，或連不上），重新同步後重做'
        }
    }
    if (-not $done) { throw '重試三次仍然 push 不上去' }
} catch {
    Write-Log "!! 失敗：$($_.Exception.Message)"
    $exitCode = 1
} finally {
    if ($haveLock) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
exit $exitCode
