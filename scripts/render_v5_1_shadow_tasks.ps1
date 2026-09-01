param([string]$OutputPath = "")
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo ".venv\Scripts\python.exe"
$json = & $python -m v5_1.scheduler_plan
if ($LASTEXITCODE -ne 0) { throw "V5.1 shadow task plan rendering failed" }
if ($OutputPath) {
    [IO.File]::WriteAllText((Join-Path $repo $OutputPath), ($json -join [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
}
$json
Write-Host "REPORT_ONLY: no Scheduled Task was created, changed, enabled, or started."
