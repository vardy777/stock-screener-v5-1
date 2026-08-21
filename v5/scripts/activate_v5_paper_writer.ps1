$ErrorActionPreference="Stop"
$root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$legacy=Join-Path $root "v4\data\p3\paper_ledger.json"
if(Test-Path $legacy){$old=Get-Content $legacy -Raw|ConvertFrom-Json;if([int]$old.event_count -ne 0){throw "V4 ledger is not empty; migration required"}}
$v5Paper=Join-Path $root "v5\data\paper"
$v5Ledger=Join-Path $v5Paper "events.json"
if(Test-Path $v5Ledger){$new=Get-Content $v5Ledger -Raw|ConvertFrom-Json;if($new.events.Count -ne 0){throw "V5 ledger is not empty; explicit reconciliation required"}}
$ownership=Join-Path $root "v5\data\ownership.json";$directory=Split-Path $ownership -Parent;New-Item -ItemType Directory -Force $directory|Out-Null
$value=[ordered]@{schema_version="v5-ownership-v1";paper_writer="v5";scheduler="v5";dashboard="v5";notifications="v5";authorized=$true;authorized_at=(Get-Date).ToString("o");reason="V4 ledger empty; V4 adapter retired; V5 strict paper single-writer activation"}
$temporary="$ownership.$PID.tmp";$json=$value|ConvertTo-Json;[IO.File]::WriteAllText($temporary,$json,[Text.UTF8Encoding]::new($false));Move-Item -LiteralPath $temporary -Destination $ownership -Force
& (Join-Path $PSScriptRoot "register_recurring_safe_tasks.ps1")|Out-Null
$paperTasks=@("AStock-V5-Paper-Sell-Daily","AStock-V5-Paper-Buy-Daily")|ForEach-Object{Get-ScheduledTask -TaskName $_}
if($paperTasks.Count -ne 2 -or @($paperTasks|Where-Object{$_.State -eq 'Disabled'}).Count){throw "V5 paper task activation failed"}
[pscustomobject]@{activated=$true;ownership=$value;paper_tasks=@($paperTasks.TaskName);v4_event_count=0;v5_event_count=0}|ConvertTo-Json -Depth 4
