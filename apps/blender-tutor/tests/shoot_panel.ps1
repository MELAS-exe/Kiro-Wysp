# Screenshots of the in-Blender Wysp panel (separate Blender, isolated profile, no Core needed).
#   apps\blender-tutor\tests\shoot_panel.ps1 [-Out docs\img] [-States empty,chat] [-UiScale 1.0]
# Never reads or writes your own Blender profile: BLENDER_USER_RESOURCE_PATH points to a temp folder.
param(
    [string]$Out = "docs\img",
    [string[]]$States = @(),
    [string]$Width = "1600",
    [string]$Height = "900"
)
$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
$blender = $env:WYSP_BLENDER
if (-not $blender) { $blender = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" }
if (-not (Test-Path $blender)) { Write-Error "Blender not found. Set WYSP_BLENDER to blender.exe"; exit 2 }
$profile = Join-Path ([System.IO.Path]::GetTempPath()) "wysp-blender-shots"
New-Item -ItemType Directory -Force $profile | Out-Null
$env:BLENDER_USER_RESOURCE_PATH = $profile
$env:PYTHONPATH = Join-Path $repo ".venv\Lib\site-packages"
$outDir = if ([System.IO.Path]::IsPathRooted($Out)) { $Out } else { Join-Path $repo $Out }
$script = Join-Path $repo "apps\blender-tutor\tests\gui_panel_states.py"
$blend = Join-Path $repo "apps\blender-tutor\demo\pumpkin.blend"
& $blender --python-use-system-env --window-geometry 0 0 $Width $Height $blend --python $script -- $outDir @States 2>&1 |
    Select-String -Pattern "GUI_|Traceback|Error|error" | ForEach-Object { $_.Line }

