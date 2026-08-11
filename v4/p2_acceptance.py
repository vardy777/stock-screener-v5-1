"""Strict offline/live acceptance checks for the P2 decision chain."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .candidate_journal import CandidateJournal
from .decision_service import execution_directive
from .push import load_notification_receipt


def validate_p2_session(
    trade_date: str,
    *,
    journal_dir: Path,
    log_dir: Path | None = None,
) -> dict[str, Any]:
    journal = CandidateJournal(journal_dir)
    chain = journal.load(trade_date)
    morning = chain.get("morning", {}) or {}
    decision = chain.get("confirmation", {}) or {}
    checks = {}
    checks["morning_schema_v1"] = morning.get("schema_version") == "morning-pool-v1"
    checks["morning_id"] = str(morning.get("pool_id", "")).startswith("mp-")
    checks["confirmation_schema_v1"] = (
        decision.get("schema_version") == "confirmation-decision-v1"
    )
    checks["decision_id"] = str(decision.get("decision_id", "")).startswith("cd-")
    checks["pool_link"] = decision.get("morning_pool_id") == morning.get("pool_id")
    morning_codes = set(morning.get("candidate_codes", []))
    confirmation_codes = set(decision.get("candidate_codes", []))
    checks["confirmation_subset"] = confirmation_codes.issubset(morning_codes)
    checks["outcome_enum"] = decision.get("outcome") in {"BUY", "EMPTY", "BLOCKED"}
    checks["reason_codes_known"] = bool(decision.get("reason_codes")) and (
        "unknown_block" not in decision.get("reason_codes", [])
    )
    checks["candidate_final_fields"] = all(
        {
            "linkage_status", "v4_paper_eligible", "v4_paper_block_reasons",
            "v4_paper_policy_version",
        }.issubset(item)
        for item in decision.get("candidates", [])
    )
    directive = execution_directive(decision)
    checks["execution_same_id"] = directive.get("decision_id") == decision.get("decision_id")
    checks["execution_same_outcome"] = directive.get("outcome") == decision.get("outcome")

    morning_receipt = load_notification_receipt(f"v4-morning:{trade_date}")
    afternoon_receipt = load_notification_receipt(f"v4-afternoon:{trade_date}")
    if morning_receipt is not None or afternoon_receipt is not None:
        checks["morning_push_same_id"] = bool(
            morning_receipt is not None
            and morning_receipt.outcome == "ACCEPTED"
            and morning_receipt.parent_entity_id == morning.get("pool_id")
        )
        checks["afternoon_push_same_id"] = bool(
            afternoon_receipt is not None
            and afternoon_receipt.outcome == "ACCEPTED"
            and afternoon_receipt.parent_entity_id == decision.get("decision_id")
        )
    elif log_dir is not None:
        # Read-only compatibility for archived pre-cutover acceptance fixtures.
        base = Path(log_dir)
        try:
            morning_log = (base / "scheduled_push_morning.log").read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            morning_log = ""
        try:
            afternoon_log = (base / "scheduled_push_afternoon.log").read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            afternoon_log = ""
        checks["morning_push_same_id"] = (
            trade_date in morning_log and f"pool_id={morning.get('pool_id')}" in morning_log
        )
        checks["afternoon_push_same_id"] = (
            trade_date in afternoon_log
            and f"decision_id={decision.get('decision_id')}" in afternoon_log
            and f"outcome={decision.get('outcome')}" in afternoon_log
        )
    return {
        "acceptance_version": "p2-session-acceptance-v1",
        "trade_date": trade_date,
        "passed": bool(checks and all(checks.values())),
        "checks": checks,
        "morning_pool_id": morning.get("pool_id"),
        "decision_id": decision.get("decision_id"),
        "outcome": decision.get("outcome"),
    }
