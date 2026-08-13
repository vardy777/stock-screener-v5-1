param([string]$TaskName="AStock-V5-Dashboard-Logon",[int]$Port=8899)
$ErrorActionPreference="Stop"
$root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runner=Join-Path $root "v5\scripts\run_v5_dashboard.ps1"
$action=New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -Port {1}' -f $runner,$Port) -WorkingDirectory $root
$trigger=New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "V5 read-only research dashboard on localhost:8899; no trading writes" -Force | Out-Null
$task=Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$valid=$task.State -ne "Disabled" -and $task.Actions.Arguments -like '*v5\scripts\run_v5_dashboard.ps1*' -and $task.Settings.ExecutionTimeLimit -eq "PT0S"
if(-not $valid){throw "V5 dashboard task acceptance failed"}
$task|Select-Object TaskName,State,@{n="Arguments";e={$_.Actions.Arguments}},@{n="ExecutionTimeLimit";e={$_.Settings.ExecutionTimeLimit}},@{n="RestartCount";e={$_.Settings.RestartCount}}
