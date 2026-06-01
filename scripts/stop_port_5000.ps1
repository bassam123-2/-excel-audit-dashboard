# Stop processes listening on port 5000 (use before restarting web_app.py)
$conns = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
if (-not $conns) {
    Write-Host "Nothing listening on port 5000."
    exit 0
}
$pids = $conns.OwningProcess | Select-Object -Unique
foreach ($procId in $pids) {
    Write-Host "Stopping PID $procId"
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
}
Write-Host "Port 5000 cleared."
