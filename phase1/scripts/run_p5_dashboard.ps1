param([switch]$Restart)
$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logDir = Join-Path $projectRoot "v4\logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$stdout = Join-Path $logDir "p5-dashboard.stdout.log"
$stderr = Join-Path $logDir "p5-dashboard.stderr.log"
$existing = Get-NetTCPConnection -LocalPort 8898 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    if (-not $Restart) { exit 0 }
    # This script is executed by the same S4U task identity as the dashboard,
    # so a manual task start is the supported atomic upgrade path.
    $existing | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
        Stop-Process -Id $_ -Force -ErrorAction Stop
    }
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if (-not (Get-NetTCPConnection -LocalPort 8898 -State Listen -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 250
    }
    if (Get-NetTCPConnection -LocalPort 8898 -State Listen -ErrorAction SilentlyContinue) { exit 13 }
}
# Keep the task process as the dashboard owner. A detached Start-Process child
# survives Stop-ScheduledTask and cannot be upgraded or recovered atomically.
$process = Start-Process -FilePath $python -ArgumentList '-X','utf8','-m','v4.p5_dashboard','--port','8898','--data-dir','v4/data' -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    if (Get-NetTCPConnection -LocalPort 8898 -State Listen -ErrorAction SilentlyContinue) {
        $process.WaitForExit()
        exit $process.ExitCode
    }
    Start-Sleep -Seconds 1
}
if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
exit 12
