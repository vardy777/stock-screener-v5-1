param([int]$Port=8899)
$ErrorActionPreference="Stop"
$root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python=Join-Path $root ".venv\Scripts\python.exe"

# A stopped/replaced Scheduled Task can leave its descendant Python listener
# alive.  Never serve stale code and never kill an unrelated process that owns
# the configured port.
$listeners=@(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
foreach($listener in $listeners){
    $process=Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $listener.OwningProcess) -ErrorAction Stop
    $command=[string]$process.CommandLine
    if($command -notlike '*-m v5.dashboard*' -or $command -notlike ("*{0}*" -f $root)){
        throw "Port $Port is owned by a non-V5 process (PID $($listener.OwningProcess)); refusing destructive takeover"
    }
    Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop
}
$deadline=(Get-Date).AddSeconds(5)
while((Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline){
    Start-Sleep -Milliseconds 100
}
if(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue){throw "V5 dashboard port $Port did not become free"}
& $python -X utf8 -m v5.dashboard --port $Port --data-dir (Join-Path $root "v5\data")
exit $LASTEXITCODE
