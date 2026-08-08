param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("buy", "sell")]
    [string]$Mode
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logDir = Join-Path $projectRoot "v4\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir ("paper-{0}-{1}.log" -f $Mode, (Get-Date -Format "yyyy-MM-dd"))

if (-not (Test-Path $python)) {
    throw "Project Python runtime not found: $python"
}

Push-Location $projectRoot
try {
    & $python "v4\scripts\paper_trade.py" $Mode *>&1 | Tee-Object -FilePath $logPath -Append
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
