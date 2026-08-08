"""Read-only legacy account validation. This module never migrates or writes."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path


def _cents(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


class LegacyAccountValidator:
    def validate(self, path: Path) -> dict:
        path = Path(path)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        errors, warnings = [], []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"schema_version": "legacy-account-validation-v1", "passed": False,
                    "source_sha256": before, "errors": [f"unreadable:{type(exc).__name__}"], "warnings": []}
        required = {"capital", "initial_capital", "positions", "history"}
        missing = sorted(required - set(payload))
        if missing:
            errors.append("missing_fields:" + ",".join(missing))
        positions = payload.get("positions", [])
        history = payload.get("history", [])
        if not isinstance(positions, list) or not isinstance(history, list):
            errors.append("positions_or_history_not_list")
            positions, history = [], []
        codes = []
        for index, row in enumerate(positions):
            code = str(row.get("code", "")).zfill(6)
            codes.append(code)
            try:
                shares = int(row.get("shares", 0)); price = _cents(row.get("buy_price", 0))
                if shares <= 0 or shares % 100 or price <= 0:
                    errors.append(f"invalid_position:{index}")
            except (ValueError, TypeError, InvalidOperation):
                errors.append(f"invalid_position:{index}")
            if "cash_out" not in row:
                warnings.append(f"legacy_fee_model_position:{index}")
        if len(codes) != len(set(codes)):
            errors.append("duplicate_open_code")
        try:
            capital, initial = _cents(payload.get("capital")), _cents(payload.get("initial_capital"))
            if capital < 0 or initial <= 0:
                errors.append("invalid_capital")
        except (InvalidOperation, TypeError):
            capital = initial = Decimal("0"); errors.append("invalid_capital")
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        return {"schema_version": "legacy-account-validation-v1", "passed": not errors,
                "read_only_verified": before == after, "source_sha256": before,
                "capital": float(capital), "initial_capital": float(initial),
                "position_count": len(positions), "history_count": len(history),
                "errors": errors, "warnings": warnings,
                "migration_performed": False, "production_cutover_performed": False}
