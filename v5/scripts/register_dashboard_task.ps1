param([string]$TaskName="AStock-V5-Dashboard-Logon",[int]$Port=8899)
$ErrorActionPreference="Stop"
$root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$pythonw=Join-Path $root ".venv\Scripts\pythonw.exe"
if(-not (Test-Path $pythonw)){throw "V5 dashboard pythonw runtime missing"}
$action=New-ScheduledTaskAction -Execute $pythonw -Argument ('-X utf8 -m v5.dashboard --port {0} --data-dir "{1}"' -f $Port,(Join-Path $root "v5\data")) -WorkingDirectory $root
$trigger=New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "V5 read-only research dashboard on localhost:8899; no trading writes" -Force | Out-Null
$task=Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$valid=$task.State -ne "Disabled" -and $task.Actions.Execute -like '*\.venv\Scripts\pythonw.exe' -and $task.Actions.Arguments -like '*-m v5.dashboard*' -and $task.Settings.ExecutionTimeLimit -eq "PT0S"
if(-not $valid){throw "V5 dashboard task acceptance failed"}
$task|Select-Object TaskName,State,@{n="Arguments";e={$_.Actions.Arguments}},@{n="ExecutionTimeLimit";e={$_.Settings.ExecutionTimeLimit}},@{n="RestartCount";e={$_.Settings.RestartCount}}
