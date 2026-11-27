#Requires -Version 7.0
<#
.SYNOPSIS
在這台電腦建立「每天補兆豐 00996A」的專用 clone 與 Windows 排程。重複執行是安全的。

.DESCRIPTION
建立的東西：
- 專用 clone：$BaseDir\repo（淺層 clone，只給排程用；帶標記檔 .megafill-clone）
- 紀錄目錄：$BaseDir\logs
- 排程工作 TWActiveETFCrawler-MegaBackfill：每天在 $At 的每個時間，以目前登入的使用者執行專用 clone 裡的
  scripts/local_megafunds_job.ps1（錯過時間會在下次可以跑的時候補跑；要登入著才會跑）

排程用這台電腦的 git 與 gh 登入狀態 push 到 main，不另外存任何憑證。
做法與維護方式見 .ai/guides/data-sources.md「兆豐：GitHub runner 被 Akamai 依來源 IP 擋」。

移除：
    Unregister-ScheduledTask -TaskName TWActiveETFCrawler-MegaBackfill -Confirm:$false
    然後刪掉 $BaseDir

.PARAMETER At
每天幾點跑（本機時間），多個時間用逗號分隔。預設 19:10,22:10：主班次（18:25）跑完之後；
第二次是兆豐當天的清單晚發布、或第一次沒成功時的補跑，已經補過就什麼都不做。

.PARAMETER SkipTask
只建立專用 clone，不註冊排程。
#>
param(
    [string]$BaseDir = (Join-Path $env:LOCALAPPDATA 'TWActiveETFCrawler\megafill'),
    [string]$At = '19:10,22:10',
    [switch]$SkipTask
)

$ErrorActionPreference = 'Stop'
$taskName = 'TWActiveETFCrawler-MegaBackfill'
$repoDir = Join-Path $BaseDir 'repo'
$sourceRepo = Split-Path $PSScriptRoot -Parent
$originUrl = (& git -C $sourceRepo remote get-url origin | Select-Object -First 1)
if ("$originUrl" -notmatch 'SheenArtem[/\\]TWActiveETFCrawler(\.git)?$') { throw "這個 repo 的 origin 不是本專案：$originUrl" }

New-Item -ItemType Directory -Force $BaseDir, (Join-Path $BaseDir 'logs') | Out-Null
if (-not (Test-Path (Join-Path $repoDir '.git'))) {
    & git clone --depth 1 --branch main $originUrl $repoDir
    if ($LASTEXITCODE -ne 0) { throw 'git clone 失敗' }
}
# 標記檔不進版控：寫進這個 clone 自己的 exclude
$marker = Join-Path $repoDir '.megafill-clone'
Set-Content -Path $marker -Value "排程專用的 clone，由 scripts/setup_local_megafunds_job.ps1 建立於 $(Get-Date -Format 'yyyy-MM-dd')。不要在這裡開發。" -Encoding utf8
$excludeFile = Join-Path $repoDir '.git\info\exclude'
if (-not (Select-String -Path $excludeFile -Pattern '^\.megafill-clone$' -Quiet -ErrorAction SilentlyContinue)) {
    Add-Content -Path $excludeFile -Value '.megafill-clone' -Encoding utf8
}
# 專用 clone 沿用這個 repo 的提交身分
foreach ($key in 'user.name', 'user.email') {
    $configValue = (& git -C $sourceRepo config --get $key)
    if ($configValue) { & git -C $repoDir config $key $configValue }
}
# 每天同步一次、每次都換掉 binary 的 DB：舊的版本不留，免得專用 clone 越長越大
& git -C $repoDir config gc.reflogExpire '3.days'
& git -C $repoDir config gc.reflogExpireUnreachable '1.day'
& git -C $repoDir config gc.pruneExpire '1.day'

if (-not $SkipTask) {
    $pwshPath = (Get-Command pwsh -ErrorAction Stop).Source
    $action = New-ScheduledTaskAction -Execute $pwshPath -WorkingDirectory $repoDir `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$repoDir\scripts\local_megafunds_job.ps1`" -RepoDir `"$repoDir`""
    $triggers = @($At -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ } |
        ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ })
    if (-not $triggers) { throw "-At 沒有任何時間：$At" }
    # job 自己最多等每日班次 20 分鐘、重做三次；3 小時還沒結束就是卡住了
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings -Force `
        -Description '每天從這台電腦補兆豐 00996A 的持股並推上 TWActiveETFCrawler 的 main（GitHub runner 被兆豐前端擋）' | Out-Null
}

Write-Host "專用 clone：$repoDir"
Write-Host "紀錄：      $(Join-Path $BaseDir 'logs')"
if (-not $SkipTask) { Write-Host "排程：      $taskName，每天 $At（Get-ScheduledTaskInfo -TaskName $taskName 可看上次結果）" }
Write-Host "手動跑一次：pwsh -File `"$repoDir\scripts\local_megafunds_job.ps1`""
