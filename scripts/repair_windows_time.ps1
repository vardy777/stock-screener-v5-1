$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Administrator privileges are required to repair Windows Time."
}

Set-Service -Name W32Time -StartupType Automatic
Start-Service -Name W32Time
w32tm /config /syncfromflags:manual /manualpeerlist:"time.windows.com,0x9 ntp.aliyun.com,0x9" /update
if ($LASTEXITCODE -ne 0) { throw "w32tm configuration failed: $LASTEXITCODE" }
w32tm /resync /force
if ($LASTEXITCODE -ne 0) { throw "w32tm resync failed: $LASTEXITCODE" }

$status = w32tm /query /status
$status | Write-Output
if ($status -match "Local CMOS Clock" -or $status -match "未指定") {
    throw "Windows Time remains unsynchronized."
}
