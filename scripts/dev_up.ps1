# Start the Wysp development stack in the background: the Core, and optionally headless Blender.
#   scripts\dev_up.ps1 [-Llm pollinations|groq|openrouter|cerebras|scripted] [-NoBlender] [-Scenario file.yaml]
# Logs: $env:TEMP\wysp_core.log / .err and wysp_blender.log. Stop everything with scripts\dev_down.ps1.
param(
    [string]$Llm = "auto",
    [string]$Scenario = "",
    [switch]$NoBlender,
    [int]$Port = 8765
)
$repo = Split-Path -Parent $PSScriptRoot
$uvDir = Join-Path $env:APPDATA "Python\Python314\Scripts"
if (Test-Path $uvDir) { $env:Path += ";$uvDir" }
$uv = (Get-Command uv -ErrorAction Stop).Source
$state = Join-Path $env:TEMP "wysp_dev_pids.txt"
& (Join-Path $PSScriptRoot "dev_down.ps1") | Out-Null

$coreArgs = @("run", "wysp", "serve", "--llm", $Llm, "--port", "$Port")
if ($Scenario) { $coreArgs += @("--scenario", $Scenario) }
$core = Start-Process -FilePath $uv -ArgumentList $coreArgs -WorkingDirectory $repo -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $env:TEMP "wysp_core.log") -RedirectStandardError (Join-Path $env:TEMP "wysp_core.err")
$pids = @($core.Id)
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try { Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 | Out-Null; break } catch { }
}
Write-Host "Core: http://127.0.0.1:$Port  (pid $($core.Id))"

if (-not $NoBlender) {
    $blender = $env:WYSP_BLENDER
    if (-not $blender) { $blender = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" }
    $scene = Join-Path $repo "apps\blender-tutor\demo\pumpkin.blend"
    if (-not (Test-Path $scene)) { & $blender -b --python (Join-Path $repo "apps\blender-tutor\demo\build_scene.py") -- --out $scene | Out-Null }
    $env:PYTHONPATH = Join-Path $repo ".venv\Lib\site-packages"
    $tokenFile = Join-Path $env:USERPROFILE ".wysp\token"
    $b = Start-Process -FilePath $blender -PassThru -WindowStyle Hidden `
        -ArgumentList @("-b", "--python-use-system-env", $scene, "--python", (Join-Path $repo "apps\blender-tutor\demo\run_adapter.py"), "--",
            "--url", "ws://127.0.0.1:$Port/ws/adapter", "--token-file", $tokenFile) `
        -RedirectStandardOutput (Join-Path $env:TEMP "wysp_blender.log") -RedirectStandardError (Join-Path $env:TEMP "wysp_blender.err")
    $pids += $b.Id
    Write-Host "Blender (headless): pid $($b.Id)"
}
$pids | Set-Content $state
Start-Sleep -Seconds 4
try {
    (Invoke-RestMethod "http://127.0.0.1:$Port/api/health").adapters | ForEach-Object { Write-Host "adapter: $($_.adapter_id) ($($_.app.name) $($_.app.version))" }
} catch { Write-Host "health check failed" }
