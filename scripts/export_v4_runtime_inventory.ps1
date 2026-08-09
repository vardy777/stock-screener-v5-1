# Read-only inventory for cutover_preflight.py. Does not register or modify tasks.
$ErrorActionPreference = "Stop"
$tasks = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like "AStock-V4-*" } | ForEach-Object {
    $start = @($_.Triggers | ForEach-Object { $_.StartBoundary } | Where-Object { $_ } | Select-Object -First 1)
    $at = if ($start.Count -gt 0) { ([datetime]$start[0]).ToString("HH:mm:ss") } else { "unknown" }
    [ordered]@{
        task_name = $_.TaskName
        at = $at
        command = ((@($_.Actions | ForEach-Object { "{0} {1}" -f $_.Execute, $_.Arguments })) -join " ; ").Trim()
        state = [string]$_.State
    }
})
$hasDashboard = @($tasks | Where-Object { $_.task_name -eq "AStock-V4-Dashboard-Logon" }).Count -gt 0
$hasPush = @($tasks | Where-Object { $_.task_name -like "AStock-V4-Push-*" }).Count -gt 0
$result = [ordered]@{
    schema_version = "v4-runtime-inventory-v1"
    read_only = $true
    tasks = $tasks
    writers = @(
        [ordered]@{ resource = "candidate_decision"; owner = "P2"; active = $hasPush }
        [ordered]@{ resource = "paper_account"; owner = "legacy_production"; active = $hasDashboard }
        [ordered]@{ resource = "task_receipts"; owner = "legacy_phase1_scripts"; active = $hasPush }
    )
    mutations_performed = $false
}
$result | ConvertTo-Json -Depth 8
