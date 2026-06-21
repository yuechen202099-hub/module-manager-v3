param(
    [string]$TaskName = "ModuleManagerV2WeeklyEvaluation",
    [string]$Change = "每周定期产品评价"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root "scripts\run-product-evaluation.ps1"
$Argument = "-NoProfile -ExecutionPolicy Bypass -File `"$Script`" -Change `"$Change`""

$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Argument -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 9am
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Generate weekly Module Manager V2 product evaluation report." -Force
Write-Host "[OK] registered scheduled task: $TaskName"
