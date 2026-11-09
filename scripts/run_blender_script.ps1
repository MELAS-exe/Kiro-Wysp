# Run a Python script inside headless Blender with the project's virtualenv packages visible.
#   scripts\run_blender_script.ps1 -Script apps\blender-tutor\tests\probe_adapter.py [-Blend apps\blender-tutor\demo\pumpkin.blend] [-Filter "PROBE"]
param(
    [Parameter(Mandatory = $true)][string]$Script,
    [string]$Blend = "",
    [string]$Filter = "",
    [string[]]$ScriptArgs = @()
)
$repo = Split-Path -Parent $PSScriptRoot
$blender = $env:WYSP_BLENDER
if (-not $blender) { $blender = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" }
if (-not (Test-Path $blender)) { Write-Error "Blender not found. Set WYSP_BLENDER to blender.exe"; exit 2 }
$env:PYTHONPATH = Join-Path $repo ".venv\Lib\site-packages"
$argsList = @("-b", "--python-use-system-env")
if ($Blend) { $argsList += (Join-Path $repo $Blend) }
$argsList += @("--python", (Join-Path $repo $Script))
if ($ScriptArgs.Count -gt 0) { $argsList += @("--") + $ScriptArgs }
$out = & $blender @argsList 2>&1
if ($Filter) { $out | Select-String -Pattern $Filter | ForEach-Object { $_.Line } } else { $out }
exit $LASTEXITCODE
