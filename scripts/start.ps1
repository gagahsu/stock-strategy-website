param([switch]$Production)
$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
$projectPath=Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectPath
$pythonPath=Join-Path $projectPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '請先建立 .venv 並安裝 requirements.txt。' }
$npmPath=(Get-Command npm.cmd).Source
$backend=Start-Process -FilePath $pythonPath -ArgumentList '-m','uvicorn','backend.api:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $projectPath -WindowStyle Hidden -PassThru
try {
    if ($Production) { & $npmPath run start } else { & $npmPath run dev }
} finally {
    $processes=@(Get-CimInstance Win32_Process)
    $ids=[System.Collections.Generic.List[int]]::new();$ids.Add($backend.Id)
    for($i=0;$i -lt $ids.Count;$i++) { foreach($child in ($processes | Where-Object ParentProcessId -eq $ids[$i])) { if($child.CommandLine -notmatch '\s-m\s+backend\.worker(?:\s|$)') { $ids.Add([int]$child.ProcessId) } } }
    for($i=$ids.Count-1;$i -ge 0;$i--) { Stop-Process -Id $ids[$i] -ErrorAction SilentlyContinue }
}
