$ErrorActionPreference="Stop"
$required=@("readiness","morning_pool","morning_push","paper_sell","feature_freeze","confirmation","confirmation_push","paper_buy","health_check","maintenance","live_acceptance")
$v4AdapterText=Get-Content (Join-Path $PSScriptRoot "..\v4\scripts\p4_task_adapter.py") -Raw
$v4ProductionRetired=[bool]($v4AdapterText -match "V4_PRODUCTION_RETIRED_V5_ONLY" -and $v4AdapterText -notmatch "production_task_runner")
$v4DashboardText=Get-Content (Join-Path $PSScriptRoot "..\phase1\scripts\run_p5_dashboard.ps1") -Raw
$v4DashboardRetired=[bool]($v4DashboardText -match "V4_DASHBOARD_RETIRED_V5_ONLY")
$v5Dashboard=Get-ScheduledTask -TaskName "AStock-V5-Dashboard-Logon" -ErrorAction SilentlyContinue
$v5DashboardSupervised=[bool]($v5Dashboard -and $v5Dashboard.State -ne "Disabled" -and $v5Dashboard.Actions.Execute -like '*\.venv\Scripts\pythonw.exe' -and $v5Dashboard.Actions.Arguments -like '*-m v5.dashboard*' -and $v5Dashboard.Settings.ExecutionTimeLimit -eq "PT0S" -and $v5Dashboard.Settings.RestartCount -ge 1)
$ownershipPath=Join-Path $PSScriptRoot "..\v5\data\ownership.json"
$ownership=if(Test-Path $ownershipPath){Get-Content $ownershipPath -Raw|ConvertFrom-Json}else{$null}
$paperEnabled=[bool]($ownership -and $ownership.authorized -eq $true -and $ownership.paper_writer -eq "v5")
$tasks=@(Get-ScheduledTask|Where-Object TaskName -Like "AStock-V5-*-Daily")
$rows=@(foreach($task in $tasks){
 $argument=[string]($task.Actions|Select-Object -First 1).Arguments
 $kind=if($argument -match 'v5_task.py"?\s+([a-z_]+)'){$Matches[1]}elseif($argument -match '-m v5\.preflight(?:\s+--trade-date\s+\d{4}-\d{2}-\d{2})?'){"readiness"}elseif($argument -match 'live_acceptance.py"?(?:\s+--trade-date\s+\d{4}-\d{2}-\d{2})?\s+--save'){"live_acceptance"}else{"unknown"}
 [pscustomobject]@{task_name=$task.TaskName;state=[string]$task.State;kind=$kind;v5_bound=[bool]($argument -match 'v5[\\/]scripts[\\/]v5_task.py|-m v5\.preflight|v5[\\/]scripts[\\/]live_acceptance.py');broker=[bool]($argument -match 'broker');allow_battery=[bool](-not $task.Settings.DisallowStartIfOnBatteries);wake=[bool]$task.Settings.WakeToRun;start_when_available=[bool]$task.Settings.StartWhenAvailable;restart_count=[int]$task.Settings.RestartCount;restart_interval=[string]$task.Settings.RestartInterval}
})
$available=@($rows|Where-Object{$_.state -ne "Disabled" -and $_.v5_bound}|ForEach-Object{$_.kind})
$complete=@($required|Where-Object{$_ -notin $available}).Count -eq 0
$unique=@($available|Group-Object|Where-Object{$_.Count -ne 1}).Count -eq 0
$settingsOk=@($rows|Where-Object{$_.kind -ne "unknown" -and (-not $_.allow_battery -or -not $_.wake -or -not $_.start_when_available -or $_.restart_count -lt 3 -or $_.restart_interval -ne "PT1M")}).Count -eq 0
$recurringReady=$paperEnabled -and $complete -and $unique -and $settingsOk -and @($rows|Where-Object{$_.broker}).Count -eq 0
$legacyNames=@("AStock-V4-Push-Morning-0925","AStock-V4-Push-Confirm-145020","AStock-V4-Sell-0930","AStock-V4-Buy-1450","AStock-V4-Signal-1449","AStock-V4-Health-Sell-0936","AStock-V4-Health-Close-1453")
$legacy=@(foreach($name in $legacyNames){$task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue;[pscustomobject]@{task_name=$name;disabled=[bool]($task -and [string]$task.State -eq "Disabled")}})
$passed=$v4ProductionRetired -and $v4DashboardRetired -and (@($legacy|Where-Object{-not $_.disabled}).Count -eq 0) -and $v5DashboardSupervised -and $recurringReady
[pscustomobject]@{schema_version="production-task-static-audit-v6";passed=$passed;v4_production_retired=$v4ProductionRetired;v4_dashboard_retired=$v4DashboardRetired;legacy_tasks=$legacy;v5_recurring_tasks=$rows;v5_recurring_ready=$recurringReady;v5_paper_writer_enabled=$paperEnabled;v5_dashboard_supervised=$v5DashboardSupervised;read_only=$true}|ConvertTo-Json -Depth 5
if(-not $passed){exit 1}
