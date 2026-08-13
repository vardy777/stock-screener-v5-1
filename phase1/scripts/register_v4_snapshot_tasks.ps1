$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$runner = Join-Path $PSScriptRoot "run_scheduled_capture.ps1"
$healthRunner = Join-Path $PSScriptRoot "run_scheduled_health.ps1"
$maintenanceRunner = Join-Path $PSScriptRoot "run_daily_maintenance.ps1"
$pushRunner = Join-Path $PSScriptRoot "run_scheduled_push.ps1"
$dashboardRunner = Join-Path $PSScriptRoot "run_dashboard_local.ps1"
$paperRunner = Join-Path $PSScriptRoot "run_scheduled_paper_trade.ps1"
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$principal = New-ScheduledTaskPrincipal `
    -UserId $identity `
    -LogonType S4U `
    -RunLevel Limited

$specifications = @(
    @{
        Name = "AStock-V4-Sell-0930"
        Mode = "sell"
        At = "09:30"
        Description = "V4 strict next-session continuous-auction sell snapshot; local runtime only."
    },
    @{
        Name = "AStock-V4-Push-Morning-0925"
        Mode = "morning"
        Runner = $pushRunner
        At = "09:25"
        ExecutionMinutes = 10
        Description = "Local 09:25 preliminary watchlist and sell reminder via PushPlus; no buy action."
    },
    @{
        Name = "AStock-V4-Paper-Sell-093020"
        Mode = "sell"
        Runner = $paperRunner
        At = "09:30:20"
        Description = "Close V4 research paper positions with fresh continuous-auction quotes; no broker order."
    },
    @{
        Name = "AStock-V4-Signal-1449"
        Mode = "signal"
        At = "14:49"
        Description = "V4 strict pre-14:50 full-market feature freeze; research data only."
    },
    @{
        Name = "AStock-V4-Buy-1450"
        Mode = "buy"
        At = "14:50"
        Description = "V4 strict 14:50 full-market buy snapshot; research data only."
    },
    @{
        Name = "AStock-V4-Push-Confirm-145020"
        Mode = "afternoon"
        Runner = $pushRunner
        At = "14:50:20"
        ExecutionMinutes = 10
        Description = "Local 14:50:20 mother-pool close confirmation via PushPlus."
    },
    @{
        Name = "AStock-V4-Paper-Buy-145040"
        Mode = "buy"
        Runner = $paperRunner
        At = "14:50:40"
        Description = "Buy linked V4 Top1 in the isolated research paper account; no broker order."
    },
    @{
        Name = "AStock-V4-Health-Sell-0936"
        Mode = "sell"
        Runner = $healthRunner
        At = "09:36"
        Description = "V4 audit-only verification of the strict sell snapshot; no trading action."
    },
    @{
        Name = "AStock-V4-Health-Close-1453"
        Mode = "close"
        Runner = $healthRunner
        At = "14:53"
        Description = "V4 audit-only verification of strict signal and buy artifacts; no trading action."
    },
    @{
        Name = "AStock-V4-Maintenance-1510"
        Runner = $maintenanceRunner
        At = "15:10"
        ExecutionMinutes = 45
        Description = "V4 research-only archive refresh, next-session context, preflight and label maintenance."
    }
)

foreach ($specification in $specifications) {
    $taskRunner = if ($specification.ContainsKey("Runner")) { $specification.Runner } else { $runner }
    $arguments = if ($specification.ContainsKey("Mode")) {
        '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -Mode {1}' -f $taskRunner, $specification.Mode
    } else {
        '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $taskRunner
    }
    $executionMinutes = if ($specification.ContainsKey("ExecutionMinutes")) {
        $specification.ExecutionMinutes
    } else {
        5
    }
    $taskSettings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -WakeToRun `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes $executionMinutes) `
        -MultipleInstances IgnoreNew
    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument $arguments `
        -WorkingDirectory $projectRoot
    $trigger = New-ScheduledTaskTrigger `
        -Weekly `
        -WeeksInterval 1 `
        -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
        -At $specification.At
    Register-ScheduledTask `
        -TaskName $specification.Name `
        -Action $action `
        -Trigger $trigger `
        -Settings $taskSettings `
        -Principal $principal `
        -Description $specification.Description `
        -Force | Out-Null
}

$dashboardAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}"' -f $dashboardRunner) `
    -WorkingDirectory $projectRoot
$dashboardTrigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$dashboardSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask `
    -TaskName "AStock-V4-Dashboard-Logon" `
    -Action $dashboardAction `
    -Trigger $dashboardTrigger `
    -Settings $dashboardSettings `
    -Principal $principal `
    -Description "Start the local V4 dashboard from the project .venv at user logon." `
    -Force | Out-Null

Get-ScheduledTask -TaskName "AStock-V4-*" | Sort-Object TaskName | ForEach-Object {
    $info = Get-ScheduledTaskInfo -TaskName $_.TaskName
    [PSCustomObject]@{
        TaskName = $_.TaskName
        State = $_.State
        NextRunTime = $info.NextRunTime
        User = $_.Principal.UserId
        LogonType = $_.Principal.LogonType
    }
} | Format-Table -AutoSize
