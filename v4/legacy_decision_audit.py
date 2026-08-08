"""Read-only audit of pre-P2 candidate journals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def audit_legacy_journal(path: Path) -> dict:
    source = Path(path)
    raw = source.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    morning = payload.get("morning", {}) or {}
    confirmation = payload.get("confirmation", {}) or {}
    morning_rows = list(morning.get("candidates", []) or [])
    confirmation_rows = list(confirmation.get("candidates", []) or [])
    morning_codes = {str(item.get("code", "")) for item in morning_rows}
    confirmation_codes = {str(item.get("code", "")) for item in confirmation_rows}
    false_link_blocks = [
        str(item.get("code", ""))
        for item in confirmation_rows
        if str(item.get("code", "")) in morning_codes
        and "未通过09:25母池链路确认" in item.get("v4_paper_block_reasons", [])
    ]
    score_changes = [
        {
            "code": str(item.get("code", "")),
            "morning_score": item.get("morning_score"),
            "confirmation_score": item.get("score"),
        }
        for item in confirmation_rows
        if item.get("morning_score") is not None and item.get("score") is not None
    ]
    is_v1 = bool(
        morning.get("schema_version") == "morning-pool-v1"
        and confirmation.get("schema_version") == "confirmation-decision-v1"
    )
    return {
        "audit_version": "legacy-decision-audit-v1",
        "source_file": source.name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "trade_date": payload.get("trade_date"),
        "morning_count": len(morning_rows),
        "confirmation_count": len(confirmation_rows),
        "confirmation_is_morning_subset": confirmation_codes.issubset(morning_codes),
        "false_link_block_codes": false_link_blocks,
        "score_changes": score_changes,
        "new_schema": is_v1,
        "promotable_to_v1": False,
        "promotable_reason": (
            "source already v1" if is_v1
            else "legacy journal lacks immutable IDs/final reason lineage; retain read-only"
        ),
    }
