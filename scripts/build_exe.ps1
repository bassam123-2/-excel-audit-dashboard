# Build Windows executable with PyInstaller
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Create .venv first, then: pip install -r requirements-dev.txt"
    exit 1
}

& $py -m pip install -q -r requirements-dev.txt
& $py -m PyInstaller ai_excel_dashboard_v3_update.spec
Write-Host "Done. Output: dist\ai_excel_dashboard_v3_update.exe"
