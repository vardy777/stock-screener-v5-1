param([datetime]$TradeDate = [datetime]"2026-08-17")
$ErrorActionPreference="Stop"
$root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python=Join-Path $root ".venv\Scripts\python.exe"
$script=Join-Path $root "v5\scripts\v5_task.py"
$universeScript=Join-Path $root "v5\scripts\v5_universe_job.py"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Administrator token required" }
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
$principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType S4U -RunLevel Limited
$specs=@(
 @("Morning-Facts","morning_pool","09:24:30"),@("Morning-Push","morning_push","09:25:20"),@("Feature-Freeze","feature_freeze","14:49:00"),@("Confirmation","confirmation","14:50:00"),@("Confirmation-Push","confirmation_push","14:50:30"),@("Health","health_check","14:53:00"),@("Maintenance","maintenance","15:10:00")
)
$date=$TradeDate.ToString("yyyy-MM-dd");$suffix=$TradeDate.ToString("yyyyMMdd")
$universeAction=New-ScheduledTaskAction -Execute $python -Argument ('-X utf8 "{0}"' -f $universeScript) -WorkingDirectory $root
$universeTrigger=New-ScheduledTaskTrigger -Once -At ([datetime]::Parse("$date 08:30:00"))
Register-ScheduledTask -TaskName "AStock-V5-Universe-Refresh-$suffix" -Action $universeAction -Trigger $universeTrigger -Settings $settings -Principal $principal -Description "V5 native daily universe preparation; no notification/paper/broker writes" -Force | Out-Null
foreach($spec in $specs){
 $name="AStock-V5-$($spec[0])-$suffix";$action=New-ScheduledTaskAction -Execute $python -Argument ('-X utf8 "{0}" {1}' -f $script,$spec[1]) -WorkingDirectory $root;$trigger=New-ScheduledTaskTrigger -Once -At ([datetime]::Parse("$date $($spec[2])"))
 Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description ("V5 safe shadow; no broker/paper writes: "+$spec[1]) -Force | Out-Null
}
$installed=@(Get-ScheduledTask -TaskName "AStock-V5-Universe-Refresh-$suffix" -ErrorAction Stop)+@($specs|ForEach-Object{Get-ScheduledTask -TaskName ("AStock-V5-$($_[0])-$suffix") -ErrorAction Stop})
if($installed.Count -ne 8){throw "V5 safe shadow registration incomplete"}
$installed|Select-Object TaskName,State,@{n="Arguments";e={$_.Actions.Arguments}}
