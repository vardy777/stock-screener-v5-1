param([string]$Prefix="AStock-V5")
$ErrorActionPreference="Stop"
$root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python=Join-Path $root ".venv\Scripts\python.exe"
$taskScript=Join-Path $root "v5\scripts\v5_task.py"
$acceptanceScript=Join-Path $root "v5\scripts\live_acceptance.py"
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$days=@('Monday','Tuesday','Wednesday','Thursday','Friday')
$specs=@(
 @("Readiness-Daily","08:30:00",'-X utf8 -m v5.preflight'),
 @("Morning-Facts-Daily","09:25:05",('-X utf8 "{0}" morning_pool' -f $taskScript)),
 @("Morning-Push-Daily","09:25:50",('-X utf8 "{0}" morning_push' -f $taskScript)),
 @("Paper-Sell-Daily","09:30:10",('-X utf8 "{0}" paper_sell' -f $taskScript)),
 @("Feature-Freeze-Daily","14:49:00",('-X utf8 "{0}" feature_freeze' -f $taskScript)),
 @("Confirmation-Daily","14:50:00",('-X utf8 "{0}" confirmation' -f $taskScript)),
 @("Confirmation-Push-Daily","14:50:30",('-X utf8 "{0}" confirmation_push' -f $taskScript)),
 @("Paper-Buy-Daily","14:50:40",('-X utf8 "{0}" paper_buy' -f $taskScript)),
 @("Health-Daily","14:53:00",('-X utf8 "{0}" health_check' -f $taskScript)),
 @("Maintenance-Daily","15:10:00",('-X utf8 "{0}" maintenance' -f $taskScript)),
 @("Live-Acceptance-Daily","15:20:00",('-X utf8 "{0}" --save' -f $acceptanceScript))
)
foreach($spec in $specs){
 $name="$Prefix-$($spec[0])";$action=New-ScheduledTaskAction -Execute $python -Argument $spec[2] -WorkingDirectory $root
 $trigger=New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $days -At ([datetime]::Parse($spec[1]))
 Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "V5 recurring production-research task; calendar-gated; local paper only; no broker or V4 write" -Force|Out-Null
}
$installed=@($specs|ForEach-Object{Get-ScheduledTask -TaskName "$Prefix-$($_[0])" -ErrorAction Stop})
if($installed.Count -ne 11 -or @($installed|Where-Object{$_.State -eq 'Disabled'}).Count){throw "V5 recurring task registration failed"}
$installed|Select TaskName,State,@{n='Arguments';e={$_.Actions.Arguments}},@{n='Trigger';e={$_.Triggers.StartBoundary}}
