param([string]$OutputRoot="backups")
$ErrorActionPreference="Stop"
$root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$stamp=Get-Date -Format "yyyyMMdd-HHmmss"
$target=Join-Path $root "$OutputRoot\v5-cutover-$stamp"
New-Item -ItemType Directory -Path $target -Force | Out-Null
Get-ScheduledTask | Where-Object {$_.TaskName -like 'AStock-V4-*' -or $_.TaskName -like 'AStock-V5-*'} | Export-Clixml (Join-Path $target "tasks.xml")
Copy-Item (Join-Path $root "docs\v5-project-state.json") (Join-Path $target "v5-project-state.json")
Copy-Item (Join-Path $root "docs\project-state.json") (Join-Path $target "v4-project-state.json")
$files=Get-ChildItem $target -File | ForEach-Object {[pscustomobject]@{Name=$_.Name;SHA256=(Get-FileHash $_.FullName -Algorithm SHA256).Hash}}
$files | ConvertTo-Json | Set-Content (Join-Path $target "manifest.json") -Encoding utf8
Write-Output $target
