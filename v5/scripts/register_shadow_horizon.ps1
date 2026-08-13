param([int]$TradingDays=5,[datetime]$StartDate=(Get-Date).Date)
$ErrorActionPreference="Stop"
if($TradingDays -lt 1 -or $TradingDays -gt 10){throw "TradingDays must be between 1 and 10"}
$root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python=Join-Path $root ".venv\Scripts\python.exe"
$calendar=Join-Path $root "v5\reference\trading_calendar_cn.csv"
$days=& $python -X utf8 -c "import csv,sys; from datetime import date; rows=list(csv.DictReader(open(sys.argv[1],encoding='utf-8-sig'))); start=sys.argv[2]; n=int(sys.argv[3]); print('\n'.join(r['date'] for r in rows if r['date']>=start and r['is_open']=='1')[:n])" $calendar $StartDate.ToString("yyyy-MM-dd") $TradingDays
if($LASTEXITCODE -ne 0 -or @($days).Count -ne $TradingDays){throw "V5 calendar horizon unavailable"}
foreach($day in $days){& (Join-Path $PSScriptRoot "register_safe_shadow_tasks.ps1") -TradeDate ([datetime]::ParseExact($day,"yyyy-MM-dd",$null)) | Out-Null;if($LASTEXITCODE -ne 0){throw "V5 shadow registration failed for $day"}}
[pscustomobject]@{schema_version="v5-shadow-horizon-v1";start_date=$StartDate.ToString("yyyy-MM-dd");trading_days=@($days);paper_tasks=0;broker_tasks=0}
