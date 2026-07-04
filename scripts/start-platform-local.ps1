param(
    [int]$Port = 52131,
    [ValidateSet("127.0.0.1", "0.0.0.0")]
    [string]$HostAddress = "127.0.0.1",
    [switch]$Restart
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$ApiDir = Join-Path $Root "v2-api"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$SeedScript = Join-Path $Root "scripts\seed-platform-terminal-demo.py"
$ProjectDraftsPath = Join-Path $Root "data\platform-project-drafts.json"
$LocalStatePath = Join-Path $Root "data\platform-terminal-demo-state-local.json"
$LogDir = Join-Path $Root "data\logs"
$OutLog = Join-Path $LogDir "uvicorn-$Port.out.log"
$ErrLog = Join-Path $LogDir "uvicorn-$Port.err.log"

if (!(Test-Path $Python)) {
    throw "Python virtual environment not found: $Python"
}
if (!(Test-Path $SeedScript)) {
    throw "Terminal demo seed script not found: $SeedScript"
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "data") | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($existing) {
    if (!$Restart) {
        Write-Host "Local platform is already listening on port $Port. Use -Restart to replace it."
        exit 0
    }
    Stop-Process -Id $existing.OwningProcess
    Start-Sleep -Seconds 2
}

$env:APP_ENV = "local"
$env:DEMO_AUTH_ENABLED = "true"
$env:STATE_BACKEND = "json"
$env:STORAGE_BACKEND = "local"
$env:PLATFORM_PROJECT_DRAFTS_PATH = $ProjectDraftsPath
$env:LOCAL_SIMULATION_STATE_PATH = $LocalStatePath

& $Python $SeedScript --team-id default-team --with-review-sample
& $Python $SeedScript --team-id demo-team --with-review-sample

$arguments = @(
    "-m",
    "uvicorn",
    "app.main:app",
    "--host $HostAddress",
    "--port $Port"
)

Start-Process `
    -FilePath $Python `
    -ArgumentList $arguments `
    -WorkingDirectory $ApiDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog

Start-Sleep -Seconds 3
$started = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (!$started) {
    Write-Host "Local platform did not start. Check logs:"
    Write-Host $ErrLog
    exit 1
}

Write-Host "Local platform started: http://127.0.0.1:$Port/platform-projects"
if ($HostAddress -eq "0.0.0.0") {
    $lanIp = Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.PrefixOrigin -ne "WellKnown" } |
        Select-Object -ExpandProperty IPAddress -First 1
    if ($lanIp) {
        Write-Host "LAN URL: http://$lanIp`:$Port/platform-projects"
    }
}
Write-Host "Project drafts: $ProjectDraftsPath"
Write-Host "Local state: $LocalStatePath"
