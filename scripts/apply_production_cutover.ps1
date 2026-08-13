param(
    [string]$ProjectRoot = "C:\Users\lisha\stock-screener",
    [string]$BackupRoot = "C:\Users\lisha\stock-screener\backups\cutover-20260809-1115"
)
$ErrorActionPreference = "Stop"
$principalCheck = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principalCheck.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Administrator token required. Run this script from an elevated PowerShell window."
}
$root = [System.IO.Path]::GetFullPath($ProjectRoot)
$backup = [System.IO.Path]::GetFullPath($BackupRoot)
if ($root -ne "C:\Users\lisha\stock-screener" -or -not $backup.StartsWith("$root\backups\cutover-")) { throw "Cutover path validation failed" }
$python = Join-Path $root ".venv\Scripts\python.exe"
$adapter = Join-Path $root "v4\scripts\p4_task_adapter.py"
$authorization = Join-Path $root "v4\data\cutover\production_authorization.json"
foreach ($required in @($python,$adapter,$authorization,(Join-Path $backup "manifest.json"))) { if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Missing required artifact: $required" } }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $identity -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 45) -MultipleInstances IgnoreNew
$dashboardSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$oldNames = @("AStock-V4-Buy-1450","AStock-V4-Dashboard-Logon","AStock-V4-Health-Close-1453","AStock-V4-Health-Sell-0936","AStock-V4-Maintenance-1510","AStock-V4-Push-Confirm-145020","AStock-V4-Push-Morning-0925","AStock-V4-Sell-0930","AStock-V4-Signal-1449")
$specs = @(
 @("AStock-V4-Morning-Decision-0925","morning_decision","09:25:00"), @("AStock-V4-Morning-Push-092520","morning_push","09:25:20"),
 @("AStock-V4-Paper-Sell-093020","paper_sell","09:30:20"), @("AStock-V4-Feature-1449","feature_freeze","14:49:00"),
 @("AStock-V4-Confirmation-Decision-145020","confirmation_decision","14:50:20"), @("AStock-V4-Confirmation-Push-145030","confirmation_push","14:50:30"),
 @("AStock-V4-Paper-Buy-145040","paper_buy","14:50:40"), @("AStock-V4-Health-1453","health_check","14:53:00"),
 @("AStock-V4-Maintenance-1510","maintenance","15:10:00")
)
try {
    foreach ($name in $oldNames) { $task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue; if ($task) { if ($task.State -eq "Running") { Stop-ScheduledTask -TaskName $name }; Disable-ScheduledTask -TaskName $name | Out-Null } }
    foreach ($spec in $specs) {
        $arguments = '-X utf8 "{0}" {1} --authorization-file "{2}"' -f $adapter,$spec[1],$authorization
        $action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $root
        $trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $spec[2]
        Register-ScheduledTask -TaskName $spec[0] -Action $action -Trigger $trigger -Settings $settings -Principal $taskPrincipal -Description ("V4 P4 authorized single-owner task: "+$spec[1]) -Force | Out-Null
    }
    $dashboardRunner = Join-Path $root "phase1\scripts\run_p5_dashboard.ps1"
    $dashboardAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $dashboardRunner) -WorkingDirectory $root
    $dashboardTrigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
    Register-ScheduledTask -TaskName "AStock-V4-Dashboard-Logon" -Action $dashboardAction -Trigger $dashboardTrigger -Settings $dashboardSettings -Principal $taskPrincipal -Description "V4 P5 read-only dashboard" -Force | Out-Null
    $oldProcess = Get-NetTCPConnection -LocalPort 8898 -State Listen -ErrorAction SilentlyContinue
    if ($oldProcess) { Stop-Process -Id $oldProcess.OwningProcess -Force }
    & $dashboardRunner
    if ($LASTEXITCODE -ne 0) { throw "P5 dashboard startup failed: $LASTEXITCODE" }
    $targetNames=@($specs | ForEach-Object {$_[0]})+"AStock-V4-Dashboard-Logon"
    $installed=@($targetNames | ForEach-Object {Get-ScheduledTask -TaskName $_ -ErrorAction Stop})
    if (($installed | Where-Object State -eq "Disabled").Count) { throw "One or more target tasks are disabled" }
    [pscustomobject]@{Status="CUTOVER_APPLIED";TargetTasks=$installed.Count;Dashboard="http://127.0.0.1:8898/";ResearchLocked=$true} | ConvertTo-Json
}
catch {
    Get-ChildItem -LiteralPath (Join-Path $backup "tasks") -Filter "*.xml" | ForEach-Object {
        $name=$_.BaseName; Register-ScheduledTask -TaskName $name -Xml (Get-Content -Raw -LiteralPath $_.FullName) -Force | Out-Null; Enable-ScheduledTask -TaskName $name | Out-Null
    }
    throw
}
