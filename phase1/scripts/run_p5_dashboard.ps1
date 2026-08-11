$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logDir = Join-Path $projectRoot "v4\logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$stdout = Join-Path $logDir "p5-dashboard.stdout.log"
$stderr = Join-Path $logDir "p5-dashboard.stderr.log"
$existing = Get-NetTCPConnection -LocalPort 8898 -State Listen -ErrorAction SilentlyContinue
if ($existing) { exit 0 }
Start-Process -FilePath $python -ArgumentList '-X','utf8','-m','v4.p5_dashboard','--port','8898','--data-dir','v4/data' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if (Get-NetTCPConnection -LocalPort 8898 -State Listen -ErrorAction SilentlyContinue) {
        exit 0
    }
    Start-Sleep -Seconds 1
}
exit 12
