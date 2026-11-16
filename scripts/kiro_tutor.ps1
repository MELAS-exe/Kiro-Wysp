# Start a kiro-cli chat that acts as the Wysp tutor's model (agent mode, see docs/agent-mode.md).
#   scripts\kiro_tutor.ps1            (the Core must be running: uv run wysp serve --llm external)
# The pairing token is read from ~/.wysp/token into WYSP_TOKEN for this process only; it is never printed.
#
# A model turn always ends eventually (length, tool-call budget, or the model simply stops), and an idle
# agent means nobody calls wait_for_user: the Panel then waits forever. So each turn runs non-interactively
# and this script starts the next one as soon as it ends. Ctrl+C stops it.
$repo = Split-Path -Parent $PSScriptRoot
$env:WYSP_TOKEN = (Get-Content (Join-Path $env:USERPROFILE ".wysp\token") -Raw).Trim()
Set-Location $repo
while ($true) {
    kiro-cli chat --agent wysp-tutor --trust-workspace --no-interactive "Start the Wysp loop now."
    Write-Host "[kiro_tutor] agent turn ended ($LASTEXITCODE), restarting in 2 s (Ctrl+C to stop)"
    Start-Sleep -Seconds 2
}
