$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logDirectory = Join-Path $projectRoot "phase1\data\logs"
$logFile = Join-Path $logDirectory "dashboard_startup.log"

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Add-Content -LiteralPath $logFile -Encoding UTF8 -Value "project .venv python is missing"
    exit 10
}

$startedAt = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
Add-Content -LiteralPath $logFile -Encoding UTF8 -Value ("[{0}] START" -f $startedAt)
Push-Location $projectRoot
$previousPythonEncoding = $env:PYTHONIOENCODING
$utf8Encoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONIOENCODING = "utf-8"
try {
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $python
    $startInfo.Arguments = '-X utf8 "start_dashboard.py"'
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
    $dashboardExitCode = $process.ExitCode
}
catch {
    Add-Content -LiteralPath $logFile -Encoding UTF8 -Value $_.Exception.ToString()
    $dashboardExitCode = 11
}
finally {
    $env:PYTHONIOENCODING = $previousPythonEncoding
    Pop-Location
}
$finishedAt = Get-Date -Format "yyyy-MM-ddTHH:mm:ssK"
Add-Content -LiteralPath $logFile -Encoding UTF8 -Value ("[{0}] END exit={1}" -f $finishedAt, $dashboardExitCode)
exit $dashboardExitCode
