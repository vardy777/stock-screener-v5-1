$ErrorActionPreference="Stop"
$root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python=Join-Path $root ".venv\Scripts\python.exe"
$script=Join-Path $root "v5\scripts\recovery_observation.py"
$action=New-ScheduledTaskAction -Execute $python -Argument ('-X utf8 "{0}"' -f $script) -WorkingDirectory $root
$trigger=New-ScheduledTaskTrigger -Once -At ([datetime]::Today.AddHours(13).AddMinutes(1))
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 8) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 1)
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "AStock-V5-Recovery-Observation-20260821" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "One-time non-strict V5 recovery observation; never eligible for confirmation or paper" -Force|Out-Null
Get-ScheduledTaskInfo -TaskName "AStock-V5-Recovery-Observation-20260821"|Select LastRunTime,NextRunTime,LastTaskResult
