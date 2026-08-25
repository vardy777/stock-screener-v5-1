"""Frozen V5 baseline registry. Changes require a new challenger, never edits."""
from __future__ import annotations
import hashlib,json,inspect
from pathlib import Path
from .funnel import FunnelPolicyV1,MOMENTUM_WEIGHT,LIQUIDITY_WEIGHT,CLOSE_LOCATION_WEIGHT

BASELINE_ID="v5_baseline_funnel_v4_frozen_2026_08_25"
PARAMETERS={"policy_version":FunnelPolicyV1().version,"min_amount":5_000_000.0,"max_candidates":20,"maximum_intraday_change":.095,"maximum_range":.15,"maximum_symbol_quote_age_seconds":120.0,"momentum_weight":MOMENTUM_WEIGHT,"liquidity_weight":LIQUIDITY_WEIGHT,"close_location_weight":CLOSE_LOCATION_WEIGHT,"confirmation_reuses_morning_rank":True,"selection":"top1","capital_fraction":1/3}
BASELINE_HASH=hashlib.sha256(json.dumps(PARAMETERS,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def registry():
    return {"schema_version":"v5-frozen-baseline-v1","baseline_id":BASELINE_ID,"frozen_at":"2026-08-25T00:00:00+08:00","parameters":PARAMETERS,"parameter_hash":BASELINE_HASH,"mutable":False,"rule":"any_parameter_change_requires_a_new_challenger"}

def assert_runtime_frozen():
    policy=FunnelPolicyV1();runtime={"policy_version":policy.version,"min_amount":policy.min_amount,"max_candidates":policy.max_candidates,"maximum_intraday_change":policy.maximum_intraday_change,"maximum_range":policy.maximum_range,"maximum_symbol_quote_age_seconds":policy.maximum_symbol_quote_age_seconds,"momentum_weight":MOMENTUM_WEIGHT,"liquidity_weight":LIQUIDITY_WEIGHT,"close_location_weight":CLOSE_LOCATION_WEIGHT,"confirmation_reuses_morning_rank":True,"selection":"top1","capital_fraction":1/3}
    manifest=json.loads((Path(__file__).parent/"reference"/"frozen_baseline_v1.json").read_text(encoding="utf-8"))
    if runtime!=PARAMETERS or manifest.get("baseline_id")!=BASELINE_ID or manifest.get("parameter_hash")!=BASELINE_HASH or manifest.get("parameters")!=PARAMETERS:raise RuntimeError("frozen baseline drift; create a challenger instead")
    from .funnel import CandidateFunnel
    from .paper import PaperEngine
    from .paper_production import PaperProduction
    functions={"CandidateFunnel.run":CandidateFunnel.run,"PaperEngine.__init__":PaperEngine.__init__,"PaperEngine.buy_order":PaperEngine.buy_order,"PaperProduction.buy":PaperProduction.buy,"PaperProduction.save_baseline":PaperProduction.save_baseline}
    hashes={name:hashlib.sha256(inspect.getsource(function).encode()).hexdigest() for name,function in functions.items()}
    if hashes!=manifest.get("protected_logic_hashes"):raise RuntimeError("frozen baseline protected logic drift; create a challenger instead")
    return True
