$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install -r .\v2-api\requirements-dev.txt
$env:PYTHONPATH = Join-Path $root "v2-api"
.\.venv\Scripts\python.exe -m pytest .\v2-api\tests -q
.\.venv\Scripts\python.exe -m compileall .\v2-api\app .\v2-api\alembic -q

