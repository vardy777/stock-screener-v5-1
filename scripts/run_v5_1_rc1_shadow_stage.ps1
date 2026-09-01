param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "preflight",
        "morning_observation",
        "morning_pool",
        "feature_freeze",
        "confirmation",
        "execution",
        "next_open_exit",
        "round_trip_acceptance",
        "health",
        "acceptance"
    )]
    [string]$Stage
)

$ErrorActionPreference = "Stop"
$releaseRoot = "C:\Users\lisha\V5_1_RC1_NATURAL_SHADOW\release"
$repositoryRoot = "C:\Users\lisha\stock-screener"
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$artifact = Join-Path $repositoryRoot "V5_1_RC1.zip"
$logRoot = "C:\Users\lisha\V5_1_RC1_NATURAL_SHADOW\logs"
$expectedArtifactSha = "092a83feb2a8b8bdf22404df409836100910197d7c9513f6338658bfc0c333c4"
$expectedReleaseManifestSha = "0d8b9eab9449671b6873936fcf875887d32e595159e289dfc8fcad1580d1d756"
$expectedDependencyLockSha = "41fdab33150f6bb1437d6d09c2b38c44560f66d82d2c4b040b0a1f6129066644"
$expectedSourceInventorySha = "290f67bc976fc89409718fccaa56c0e2d759ada3ba801fc99d31a4299f03f681"
$expectedConfigHash = "9e858726c0e521a6e22aeda105d5be3e2d102855e5d938691078901d090a1d07"

if (-not (Test-Path -LiteralPath $releaseRoot -PathType Container)) {
    throw "Frozen RC1 release root is missing"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Pinned Python runtime is missing"
}
$actualArtifactSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifact).Hash.ToLowerInvariant()
if ($actualArtifactSha -ne $expectedArtifactSha) {
    throw "Frozen RC1 artifact identity mismatch"
}
$actualReleaseManifestSha = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $releaseRoot "RELEASE_MANIFEST.json")).Hash.ToLowerInvariant()
$actualDependencyLockSha = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $releaseRoot "requirements-v5_1.lock")).Hash.ToLowerInvariant()
$actualSourceInventorySha = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $releaseRoot "SOURCE_INVENTORY.json")).Hash.ToLowerInvariant()
$releaseManifest = Get-Content -Raw -LiteralPath (Join-Path $releaseRoot "RELEASE_MANIFEST.json") | ConvertFrom-Json
if ($actualReleaseManifestSha -ne $expectedReleaseManifestSha -or
    $actualDependencyLockSha -ne $expectedDependencyLockSha -or
    $actualSourceInventorySha -ne $expectedSourceInventorySha -or
    $releaseManifest.config_hash -ne $expectedConfigHash -or
    $releaseManifest.git_sha -ne "14cbcf2615a68a50789997e26527f82074a2ca6e" -or
    $releaseManifest.git_tree_sha -ne "985930b9bc0786393004d8e3ab76d83286537b54") {
    throw "Frozen RC1 release identity mismatch"
}

$stamp = Get-Date -Format "yyyyMMddTHHmmss.fffK"
$safeStamp = $stamp -replace ":", "-"
$logPath = Join-Path $logRoot ("{0}_{1}.log" -f $safeStamp, $Stage)
$startedAt = (Get-Date).ToString("o")

# Task Scheduler's schtasks.exe interface is minute-granular. Preserve the
# frozen runtime's point-in-time contract by delaying only within the current
# natural minute; never chase a missed minute or alter the runtime clock.
$targetSecond = if ($Stage -eq "execution") { 40 } elseif ($Stage -eq "next_open_exit") { 10 } else { 0 }
$current = Get-Date
if ($targetSecond -gt 0 -and $current.Second -lt $targetSecond) {
    Start-Sleep -Seconds ($targetSecond - $current.Second)
}

Push-Location $releaseRoot
try {
    $output = & $python -m v5_1.task_runner $Stage --mode SHADOW 2>&1
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

$completedAt = (Get-Date).ToString("o")
$record = @(
    "release_id=V5.1-RC1"
    "artifact_sha256=$actualArtifactSha"
    "stage=$Stage"
    "started_at=$startedAt"
    "completed_at=$completedAt"
    "exit_code=$exitCode"
    "output_begin"
    ($output | Out-String).TrimEnd()
    "output_end"
) -join [Environment]::NewLine
[System.IO.File]::WriteAllText($logPath, $record + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

Write-Output $record
exit $exitCode
