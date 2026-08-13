param([datetime]$TradeDate = [datetime]"2026-08-17")
$ErrorActionPreference="Stop"
$root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python=Join-Path $root ".venv\Scripts\python.exe"
$script=Join-Path $root "v5\scripts\v5_task.py"
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2)
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$specs=@(
 @("Morning-Facts","morning_pool","09:24:30"),@("Morning-Push","morning_push","09:25:20"),@("Feature-Freeze","feature_freeze","14:49:00"),@("Confirmation","confirmation","14:50:00"),@("Confirmation-Push","confirmation_push","14:50:30"),@("Health","health_check","14:53:00"),@("Maintenance","maintenance","15:10:00")
)
$date=$TradeDate.ToString("yyyy-MM-dd");$suffix=$TradeDate.ToString("yyyyMMdd")
$readinessName="AStock-V5-Readiness-$suffix"
$readinessAction=New-ScheduledTaskAction -Execute $python -Argument ('-X utf8 -m v5.preflight --trade-date {0}' -f $date) -WorkingDirectory $root
$readinessTrigger=New-ScheduledTaskTrigger -Once -At ([datetime]::Parse("$date 08:30:00"))
Register-ScheduledTask -TaskName $readinessName -Action $readinessAction -Trigger $readinessTrigger -Settings $settings -Principal $principal -Description "V5 native universe readiness; diagnostic and fail-closed; no notification, paper or broker writes" -Force | Out-Null
foreach($spec in $specs){
 $name="AStock-V5-$($spec[0])-$suffix";$action=New-ScheduledTaskAction -Execute $python -Argument ('-X utf8 "{0}" {1}' -f $script,$spec[1]) -WorkingDirectory $root;$trigger=New-ScheduledTaskTrigger -Once -At ([datetime]::Parse("$date $($spec[2])"))
 Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description ("V5 safe shadow; no broker/paper writes: "+$spec[1]) -Force | Out-Null
}
$readiness=Get-ScheduledTask -TaskName $readinessName -ErrorAction Stop
$installed=@($specs|ForEach-Object{Get-ScheduledTask -TaskName ("AStock-V5-$($_[0])-$suffix") -ErrorAction Stop})
if($installed.Count -ne 7 -or $readiness.State -eq "Disabled" -or $readiness.Actions.Arguments -notlike "*--trade-date $date*" -or $readiness.Settings.RestartCount -lt 3){throw "V5 safe shadow registration incomplete"}
@($readiness)+$installed|Select-Object TaskName,State,@{n="Arguments";e={$_.Actions.Arguments}}
