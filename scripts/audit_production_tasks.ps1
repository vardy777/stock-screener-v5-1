$ErrorActionPreference = "Stop"
$expected = @(
  "AStock-V4-Morning-Decision-0925","AStock-V4-Morning-Push-092520","AStock-V4-Paper-Sell-093020",
  "AStock-V4-Feature-1449","AStock-V4-Confirmation-Decision-145020","AStock-V4-Confirmation-Push-145030",
  "AStock-V4-Paper-Buy-145040","AStock-V4-Health-1453","AStock-V4-Maintenance-1510"
)
$legacy = @("AStock-V4-Push-Morning-0925","AStock-V4-Push-Confirm-145020","AStock-V4-Sell-0930","AStock-V4-Buy-1450","AStock-V4-Signal-1449","AStock-V4-Health-Sell-0936","AStock-V4-Health-Close-1453")
$rows = foreach ($name in $expected) {
  $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  $action = if ($task) { $task.Actions | Select-Object -First 1 } else { $null }
  [pscustomobject]@{ task_name=$name; exists=[bool]$task; state=if($task){[string]$task.State}else{"MISSING"};
    adapter_bound=[bool]($action -and $action.Arguments -like '*v4\scripts\p4_task_adapter.py*') }
}
$legacyRows = foreach ($name in $legacy) {
  $task=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
  [pscustomobject]@{task_name=$name; disabled=[bool]($task -and [string]$task.State -eq "Disabled")}
}
$dashboard=Get-ScheduledTask -TaskName "AStock-V4-Dashboard-Logon" -ErrorAction SilentlyContinue
$dashboardSupervised=[bool]($dashboard -and $dashboard.State -ne "Disabled" -and $dashboard.Settings.ExecutionTimeLimit -eq "PT0S")
$v5Dashboard=Get-ScheduledTask -TaskName "AStock-V5-Dashboard-Logon" -ErrorAction SilentlyContinue
$v5DashboardSupervised=[bool]($v5Dashboard -and $v5Dashboard.State -ne "Disabled" -and $v5Dashboard.Actions.Execute -like '*\.venv\Scripts\pythonw.exe' -and $v5Dashboard.Actions.Arguments -like '*-m v5.dashboard*' -and $v5Dashboard.Settings.ExecutionTimeLimit -eq "PT0S" -and $v5Dashboard.Settings.RestartCount -ge 1)
$v5Tasks=@(Get-ScheduledTask -TaskName "AStock-V5-*" -ErrorAction SilentlyContinue)
$requiredV5=@("readiness","morning_pool","morning_push","feature_freeze","confirmation","confirmation_push","health_check","maintenance","live_acceptance")
$v5Rows=foreach($task in $v5Tasks){
 $action=$task.Actions|Select-Object -First 1;$argument=[string]$action.Arguments
 $kind=if($argument -match 'v5_task.py"?\s+([a-z_]+)'){$Matches[1]}elseif($argument -match '-m v5\.preflight\s+--trade-date\s+(\d{4}-\d{2}-\d{2})'){"readiness"}elseif($argument -match 'live_acceptance.py"?\s+--trade-date\s+(\d{4}-\d{2}-\d{2})\s+--save'){"live_acceptance"}elseif($argument -match '-m v5\.preflight'){"preflight"}else{"unknown"}
 [pscustomobject]@{task_name=$task.TaskName;state=[string]$task.State;kind=$kind;v5_bound=[bool]($argument -match 'v5[\\/]scripts[\\/]v5_task.py|-m v5\.preflight|v5[\\/]scripts[\\/]live_acceptance.py');paper_or_broker=[bool]($argument -match 'paper_buy|paper_sell|broker');allow_battery=[bool](-not $task.Settings.DisallowStartIfOnBatteries);wake_to_run=[bool]$task.Settings.WakeToRun;restart_count=[int]$task.Settings.RestartCount}
}
$targetDate=(Get-Date).Date.AddDays(1)
while($targetDate.DayOfWeek -in @([DayOfWeek]::Saturday,[DayOfWeek]::Sunday)){$targetDate=$targetDate.AddDays(1)}
$targetSuffix=$targetDate.ToString("yyyyMMdd")
$targetRows=@($v5Rows|Where-Object{$_.task_name -like "*-$targetSuffix"})
$availableKinds=@($targetRows|Where-Object{$_.state -ne "Disabled" -and $_.v5_bound}|ForEach-Object{$_.kind})
$readinessDateCorrect=@($targetRows|Where-Object{$_.kind -eq "readiness" -and $_.task_name -eq "AStock-V5-Readiness-$targetSuffix"}).Count -eq 1
$v5ShadowReady=(@($requiredV5|Where-Object{$_ -notin $availableKinds}).Count -eq 0) -and (@($availableKinds|Group-Object|Where-Object{$_.Count -ne 1}).Count -eq 0) -and $readinessDateCorrect -and (@($targetRows|Where-Object{$_.paper_or_broker}).Count -eq 0) -and (@($targetRows|Where-Object{$_.kind -ne "unknown" -and (-not $_.allow_battery -or -not $_.wake_to_run -or $_.restart_count -lt 3)}).Count -eq 0)
$passed=(@($rows | Where-Object {-not $_.exists -or $_.state -eq "Disabled" -or -not $_.adapter_bound}).Count -eq 0) -and (@($legacyRows | Where-Object {-not $_.disabled}).Count -eq 0) -and $dashboardSupervised -and $v5DashboardSupervised -and $v5ShadowReady
[pscustomobject]@{schema_version="production-task-static-audit-v3";passed=$passed;transition_v4_tasks=$rows;legacy_tasks=$legacyRows;v5_target_date=$targetDate.ToString("yyyy-MM-dd");v5_shadow_tasks=$targetRows;v5_shadow_ready=$v5ShadowReady;v5_paper_writer_enabled=$false;v4_dashboard_supervised=$dashboardSupervised;v5_dashboard_supervised=$v5DashboardSupervised;read_only=$true} | ConvertTo-Json -Depth 5
if(-not $passed){exit 1}
