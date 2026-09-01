"""V5.1 fact root; V5 legacy directories are never read as V5.1 facts."""
from pathlib import Path
from shared_core.core import ContractViolation
from .facts import save_immutable

KINDS={"daily_security_statuses":"status_id","tradability":"tradability_id","morning_pools":"pool_id","confirmations":"confirmation_id","closescan_candidates":"candidate_fact_id","closescan_selections":"selection_id","closescan_runs":"run_id","execution_observations":"observation_id","execution_results":"execution_result_id","execution_rejections":"rejection_id","exit_decisions":"exit_decision_id","production_runs":"run_id","production_failures":"failure_id","health_facts":"health_id","acceptance_facts":"acceptance_id","round_trip_acceptances":"round_trip_acceptance_id","stage_outcomes":"stage_outcome_id","notification_receipts":"receipt_id","comparisons":"comparison_id"}
class V51FactStore:
    def __init__(self,root):self.root=Path(root)
    def save(self,kind,fact):
        if kind not in KINDS:raise ContractViolation("unsupported V5.1 fact kind")
        value=fact.to_dict() if hasattr(fact,"to_dict") else dict(fact);entity=value.get(KINDS[kind]);day=value.get("trade_date")
        if value.get("system_version")!="5.1" or not entity or not day:raise ContractViolation("V5.1 versioned content-addressed fact required")
        symbol=value.get("symbol")
        folder=self.root/kind/day/(str(symbol) if kind=="daily_security_statuses" else "")
        return save_immutable(folder/f"{entity}.json",value)
