# Start the pieces of the demo that can be started from a script, idempotently: running it twice changes nothing.
#   scripts\demo_up.ps1 [-Mode side|compact|full] [-Llm external|auto|scripted] [-NoPanel] [-NoTutor] [-Scenario file.yaml]
# - Core: started only if http://127.0.0.1:<port>/api/health does not answer (an existing Core is never restarted).
# - Tutor loop (Kiro as the model, only with -Llm external): started in its own window only if none is running.
# - Panel: opened as a Chrome app window (scripts\open_panel.py) only if none was opened by this script before.
# Blender, IntelliJ and Chrome (extension) are opened by hand: see docs\demo-setup.md. This script then lists the adapters.
# Stop the Core with scripts\dev_down.ps1.
param(
    [ValidateSet("side", "compact", "full")][string]$Mode = "side",
    [string]$Llm = "external",
    [string]$Scenario = "",
    [switch]$NoPanel,
    [switch]$NoTutor,
    [int]$Port = 8765
)
$repo = Split-Path -Parent $PSScriptRoot
$uvDir = Join-Path $env:APPDATA "Python\Python314\Scripts"
if (Test-Path $uvDir) { $env:Path += ";$uvDir" }
$uv = (Get-Command uv -ErrorAction Stop).Source
$base = "http://127.0.0.1:$Port"

function Get-Health {
    try { return Invoke-RestMethod "$base/api/health" -TimeoutSec 2 } catch { return $null }
}

# 1. Core
if (Get-Health) {
    Write-Host "Core: already running on $base (left untouched)"
} else {
    $coreArgs = @("run", "wysp", "serve", "--llm", $Llm, "--port", "$Port")
    if ($Scenario) { $coreArgs += @("--scenario", $Scenario) }
    $core = Start-Process -FilePath $uv -ArgumentList $coreArgs -WorkingDirectory $repo -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $env:TEMP "wysp_core.log") -RedirectStandardError (Join-Path $env:TEMP "wysp_core.err")
    $state = Join-Path $env:TEMP "wysp_dev_pids.txt"
    Add-Content $state $core.Id
    for ($i = 0; $i -lt 60 -and -not (Get-Health); $i++) { Start-Sleep -Milliseconds 500 }
    if (Get-Health) { Write-Host "Core: started on $base (pid $($core.Id), llm $Llm)" }
    else { Write-Host "Core: did not answer in 30 s, see $env:TEMP\wysp_core.err"; exit 1 }
}

# 2. Tutor loop (only meaningful when the Core waits for an external model)
if ($Llm -eq "external" -and -not $NoTutor) {
    $running = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "kiro_tutor\.ps1" }
    if ($running) {
        Write-Host "Tutor loop: already running (pid $($running[0].ProcessId))"
    } else {
        Start-Process powershell -WorkingDirectory $repo -ArgumentList @("-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "kiro_tutor.ps1"))
        Write-Host "Tutor loop: started in a new window (close it to stop)"
    }
}

# 3. Panel window
if (-not $NoPanel) {
    $marker = Join-Path $env:TEMP "wysp_panel_opened.txt"
    $open = (Test-Path $marker) -and ((Get-Content $marker -ErrorAction SilentlyContinue) -eq "$Mode@$Port") -and
        (Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "--app=http://127.0.0.1:$Port" })
    if ($open) {
        Write-Host "Panel: already open ($Mode)"
    } else {
        & $uv run --no-project python (Join-Path $PSScriptRoot "open_panel.py") --mode $Mode --port $Port
        "$Mode@$Port" | Set-Content $marker
    }
}

# 4. What is connected
Start-Sleep -Seconds 1
$h = Get-Health
if ($h -and $h.adapters) {
    $h.adapters | ForEach-Object { Write-Host "adapter: $($_.adapter_id) ($($_.app.name) $($_.app.version))" }
} else {
    Write-Host "No adapter connected yet: open Blender (extension enabled), IntelliJ (Wysp tool window) or the Chrome page. See docs\demo-setup.md."
}
