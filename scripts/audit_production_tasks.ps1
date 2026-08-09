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
$passed=(@($rows | Where-Object {-not $_.exists -or $_.state -eq "Disabled" -or -not $_.adapter_bound}).Count -eq 0) -and (@($legacyRows | Where-Object {-not $_.disabled}).Count -eq 0)
[pscustomobject]@{schema_version="production-task-static-audit-v1";passed=$passed;active_tasks=$rows;legacy_tasks=$legacyRows;read_only=$true} | ConvertTo-Json -Depth 5
if(-not $passed){exit 1}
