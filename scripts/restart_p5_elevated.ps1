$ErrorActionPreference="Stop"
$principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw "Administrator token required"}
$connection=Get-NetTCPConnection -LocalPort 8898 -State Listen -ErrorAction SilentlyContinue
if($connection){Stop-Process -Id $connection.OwningProcess -Force}
& "C:\Users\lisha\stock-screener\phase1\scripts\run_p5_dashboard.ps1"
exit $LASTEXITCODE
