param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("sell", "close")]
    [string]$Mode
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logDirectory = Join-Path $projectRoot "phase1\data\logs"
$logFile = Join-Path $logDirectory ("scheduled_health_{0}.log" -f $Mode)
$tradeDate = Get-Date -Format "yyyy-MM-dd"
$sessions = if ($Mode -eq "sell") { "sell" } else { "signal,buy" }

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$startedAt = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
Add-Content -LiteralPath $logFile -Encoding UTF8 -Value ("[{0}] START mode={1} sessions={2} trade_date={3}" -f $startedAt, $Mode, $sessions, $tradeDate)

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Add-Content -LiteralPath $logFile -Encoding UTF8 -Value "project .venv python is missing"
    exit 10
}

Push-Location $projectRoot
$previousPythonEncoding = $env:PYTHONIOENCODING
$utf8Encoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONIOENCODING = "utf-8"
try {
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $python
    $startInfo.Arguments = '-X utf8 "phase1\scripts\verify_capture_health.py" --trade-date {0} --sessions "{1}" --notify-failure' -f $tradeDate, $sessions
    $startInfo.WorkingDirectory = $projectRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.StandardOutputEncoding = $utf8Encoding
    $startInfo.StandardErrorEncoding = $utf8Encoding
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    $null = $process.Start()
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $stdout = $stdoutTask.Result
    $stderr = $stderrTask.Result
    if ($stdout) { Add-Content -LiteralPath $logFile -Encoding UTF8 -Value $stdout.TrimEnd() }
    if ($stderr) { Add-Content -LiteralPath $logFile -Encoding UTF8 -Value $stderr.TrimEnd() }
    $healthExitCode = $process.ExitCode
}
catch {
    Add-Content -LiteralPath $logFile -Encoding UTF8 -Value $_.Exception.ToString()
    $healthExitCode = 11
}
finally {
    $env:PYTHONIOENCODING = $previousPythonEncoding
    Pop-Location
}

$finishedAt = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
Add-Content -LiteralPath $logFile -Encoding UTF8 -Value ("[{0}] END mode={1} exit={2}" -f $finishedAt, $Mode, $healthExitCode)
exit $healthExitCode
