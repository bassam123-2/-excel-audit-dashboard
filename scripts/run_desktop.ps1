# Deprecated desktop launcher kept for transition only
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Desktop mode is deprecated in Django migration. Use .\scripts\run_web.ps1"
