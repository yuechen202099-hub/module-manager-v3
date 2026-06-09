$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install -r .\v2-api\requirements-dev.txt

$env:PYTHONPATH = Join-Path $root "v2-api"
Start-Process -FilePath ".\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload" `
    -WorkingDirectory (Join-Path $root "v2-api") `
    -WindowStyle Hidden

Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:8000/v201"

