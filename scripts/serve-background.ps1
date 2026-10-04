param([int[]]$ReplaceProcessIds=@())
$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
$projectPath=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectPath
function Stop-OwnedTree([int]$rootPid) {
    $processes=@(Get-CimInstance Win32_Process)
    $root=$processes | Where-Object ProcessId -eq $rootPid
    if (-not $root) { return }
    if ($root.CommandLine -notlike "*$projectPath*" -and $root.CommandLine -notmatch 'npm.cmd.*run start') { throw '拒絕停止非本次建立的服務。' }
    $ids=[System.Collections.Generic.List[int]]::new();$ids.Add($rootPid)
    for($i=0;$i -lt $ids.Count;$i++) { foreach($child in ($processes | Where-Object ParentProcessId -eq $ids[$i])) { if($child.CommandLine -notmatch '\s-m\s+backend\.(?:worker|official_history)(?:\s|$)') { $ids.Add([int]$child.ProcessId) } } }
    for($i=$ids.Count-1;$i -ge 0;$i--) { Stop-Process -Id $ids[$i] -ErrorAction SilentlyContinue }
}
foreach($taskProcessId in $ReplaceProcessIds) { Stop-OwnedTree $taskProcessId }
$pythonPath=Join-Path $projectPath '.venv\Scripts\python.exe'
$npmPath=(Get-Command npm.cmd).Source
$backend=Start-Process -FilePath $pythonPath -ArgumentList '-m','uvicorn','backend.api:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $projectPath -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectPath 'data/backend.log') -RedirectStandardError (Join-Path $projectPath 'data/backend-error.log')
$frontend=Start-Process -FilePath $npmPath -ArgumentList 'run','start' -WorkingDirectory $projectPath -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectPath 'data/frontend.log') -RedirectStandardError (Join-Path $projectPath 'data/frontend-error.log')
@{backend=$backend.Id;frontend=$frontend.Id;started_at=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectPath 'data/local-services.json') -Encoding utf8
for($attempt=0;$attempt -lt 20;$attempt++) {
    try {
        $apiHealth=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
        $webHealth=Invoke-RestMethod -Uri 'http://127.0.0.1:3000/api/health' -TimeoutSec 2
        if($apiHealth.status -eq 'ok' -and $webHealth.status -eq 'ok') { break }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if($attempt -ge 20) { throw '服務健康檢查失敗，請查看 data/backend-error.log 與 data/frontend-error.log。' }
Write-Output '個人網站背景服務已啟動：http://127.0.0.1:3000'
