param([int]$Port=8899,[string]$DataDir="v5/data")
$ErrorActionPreference="Stop"
$root=(Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python=Join-Path $root ".venv\Scripts\python.exe"
& $python -X utf8 -m v5.dashboard --port $Port --data-dir $DataDir
exit $LASTEXITCODE
