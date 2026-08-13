$ErrorActionPreference = "Stop"
$name = "AStock-V4-Dashboard-Logon"
$task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
Set-ScheduledTask -TaskName $name -Action $task.Actions -Trigger $task.Triggers -Principal $task.Principal -Settings $settings | Out-Null
$updated = Get-ScheduledTask -TaskName $name
if ($updated.Settings.ExecutionTimeLimit -ne "PT0S") { throw "Dashboard task limit repair failed" }
