param(
    [string]$Change = "",
    [int]$Budget = 130,
    [switch]$SkipChecks
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = "python"
if (Test-Path ".venv\Scripts\python.exe") {
    $Python = ".venv\Scripts\python.exe"
}

$ArgsList = @("scripts\generate_product_evaluation.py", "--budget", $Budget.ToString())
if ($Change.Trim().Length -gt 0) {
    $ArgsList += @("--change", $Change)
}
if (-not $SkipChecks) {
    $ArgsList += "--run-checks"
}

& $Python @ArgsList
