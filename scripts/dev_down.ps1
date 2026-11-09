# Stop the processes started by scripts\dev_up.ps1 (Core and headless Blender) and anything on the Core port.
param([int]$Port = 8765)
$state = Join-Path $env:TEMP "wysp_dev_pids.txt"
$stopped = @()
if (Test-Path $state) {
    foreach ($id in (Get-Content $state)) {
        $p = Get-Process -Id ([int]$id) -ErrorAction SilentlyContinue
        if ($p) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; $stopped += $p.Id }
    }
    Remove-Item $state -ErrorAction SilentlyContinue
}
# uv spawns the real server as a child process: stop whatever still listens on the port.
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    $stopped += $_.OwningProcess
}
Get-CimInstance Win32_Process -Filter "Name='blender.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "run_adapter.py" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $stopped += $_.ProcessId }
if ($stopped.Count) { Write-Host "stopped: $($stopped | Sort-Object -Unique)" } else { Write-Host "nothing was running" }
