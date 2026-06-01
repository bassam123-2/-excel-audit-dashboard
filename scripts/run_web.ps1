# Start Flask web dashboard on http://127.0.0.1:5000
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Virtual env not found. Run: python -m venv .venv ; .\.venv\Scripts\pip install -r requirements.txt"
    exit 1
}

Write-Host "Starting web server from $Root"
& $py web_app.py
