$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Virtual env not found. Run setup first."
    exit 1
}

& $py manage.py check --database default
& $py manage.py shell -c "from django.db import connection; connection.cursor(); print('MySQL connection OK')"
