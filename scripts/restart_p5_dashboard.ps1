$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
& (Join-Path $root "phase1\scripts\run_p5_dashboard.ps1") -Restart
