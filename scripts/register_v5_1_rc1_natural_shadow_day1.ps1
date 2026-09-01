$ErrorActionPreference = "Stop"

$runner = "C:\Users\lisha\V5_1_RC1_NATURAL_SHADOW\orchestration\run_v5_1_rc1_shadow_stage.ps1"
$entries = @(
    @{ Name = "V51-RC1-Shadow-Preflight-0810"; Date = "2026/09/02"; Time = "08:10"; Stage = "preflight" },
    @{ Name = "V51-RC1-Shadow-Preflight-0830"; Date = "2026/09/02"; Time = "08:30"; Stage = "preflight" },
    @{ Name = "V51-RC1-Shadow-Preflight-0850"; Date = "2026/09/02"; Time = "08:50"; Stage = "preflight" },
    @{ Name = "V51-RC1-Shadow-Preflight-0905"; Date = "2026/09/02"; Time = "09:05"; Stage = "preflight" },
    @{ Name = "V51-RC1-Shadow-Preflight-0920"; Date = "2026/09/02"; Time = "09:20"; Stage = "preflight" },
    @{ Name = "V51-RC1-Shadow-MorningObservation"; Date = "2026/09/02"; Time = "09:30"; Stage = "morning_observation" },
    @{ Name = "V51-RC1-Shadow-MorningPool"; Date = "2026/09/02"; Time = "09:35"; Stage = "morning_pool" },
    @{ Name = "V51-RC1-Shadow-FeatureFreeze"; Date = "2026/09/02"; Time = "14:49"; Stage = "feature_freeze" },
    @{ Name = "V51-RC1-Shadow-Confirmation"; Date = "2026/09/02"; Time = "14:50"; Stage = "confirmation" },
    @{ Name = "V51-RC1-Shadow-Execution"; Date = "2026/09/02"; Time = "14:50"; Stage = "execution" },
    @{ Name = "V51-RC1-Shadow-Health"; Date = "2026/09/02"; Time = "14:53"; Stage = "health" },
    @{ Name = "V51-RC1-Shadow-PreliminaryAcceptance"; Date = "2026/09/02"; Time = "15:20"; Stage = "acceptance" },
    @{ Name = "V51-RC1-Shadow-NextOpenExit"; Date = "2026/09/03"; Time = "09:30"; Stage = "next_open_exit" },
    @{ Name = "V51-RC1-Shadow-RoundTripAcceptance"; Date = "2026/09/03"; Time = "09:31"; Stage = "round_trip_acceptance" }
)

foreach ($entry in $entries) {
    $action = 'powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -Stage {1}' -f $runner, $entry.Stage
    & schtasks.exe /Create /TN $entry.Name /TR $action /SC ONCE /SD $entry.Date /ST $entry.Time /RL LIMITED /F | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to register $($entry.Name)"
    }
}

Write-Output ("Registered {0} one-shot Natural SHADOW tasks." -f $entries.Count)
