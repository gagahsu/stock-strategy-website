$ErrorActionPreference='Stop'
$projectPath=Split-Path -Parent $PSScriptRoot
$pythonPath=Join-Path $projectPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '缺少 Python 虛擬環境。' }
$action=New-ScheduledTaskAction -Execute $pythonPath -Argument '-m backend.daily_job' -WorkingDirectory $projectPath
$triggers=@(New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At '15:30'; New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At '20:00')
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 4)
Register-ScheduledTask -TaskName 'StockStrategyDaily' -Action $action -Trigger $triggers -Settings $settings -Description '台股策略：每日資料、掃描及持股出場提醒' -Force | Out-Null
Write-Output '已建立平日15:30與20:00的個人排程（依本機時間）。'
