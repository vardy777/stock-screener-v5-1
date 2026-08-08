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
        open_cost = Decimal("0")
        for index, row in enumerate(positions):
            code = str(row.get("code", "")).zfill(6)
            codes.append(code)
            try:
                shares = int(row.get("shares", 0)); price = _cents(row.get("buy_price", 0))
                if shares <= 0 or shares % 100 or price <= 0:
                    errors.append(f"invalid_position:{index}")
                open_cost += _cents(row.get("cost", price * shares))
            except (ValueError, TypeError, InvalidOperation):
                errors.append(f"invalid_position:{index}")
            if "cash_out" not in row:
                warnings.append(f"legacy_fee_model_position:{index}")
        if len(codes) != len(set(codes)):
            errors.append("duplicate_open_code")
        history_pnl = Decimal("0")
        same_day_count = 0
        for index, row in enumerate(history):
            try:
                shares = int(row.get("shares", 0))
                if shares <= 0 or shares % 100:
                    errors.append(f"invalid_history:{index}")
                history_pnl += _cents(row.get("pnl_amount", 0))
            except (ValueError, TypeError, InvalidOperation):
                errors.append(f"invalid_history:{index}")
            if row.get("buy_date") == row.get("sell_date"):
                same_day_count += 1
                warnings.append(f"t_plus_one_incompatible_history:{index}")
        try:
            capital, initial = _cents(payload.get("capital")), _cents(payload.get("initial_capital"))
            if capital < 0 or initial <= 0:
                errors.append("invalid_capital")
        except (InvalidOperation, TypeError):
            capital = initial = Decimal("0"); errors.append("invalid_capital")
        account_equity = (capital + open_cost).quantize(Decimal("0.01"))
        pnl_equity = (initial + history_pnl).quantize(Decimal("0.01"))
        if account_equity != pnl_equity:
            errors.append("equity_history_reconciliation_mismatch")
        daily = payload.get("daily_pnl", [])
        if daily:
            try:
                if _cents(daily[-1].get("end_capital")) != account_equity:
                    errors.append("daily_equity_reconciliation_mismatch")
            except (InvalidOperation, TypeError):
                errors.append("invalid_daily_equity")
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        return {"schema_version": "legacy-account-validation-v1", "passed": not errors,
                "read_only_verified": before == after, "source_sha256": before,
                "capital": float(capital), "initial_capital": float(initial),
                "account_equity": float(account_equity), "history_pnl": float(history_pnl),
                "position_count": len(positions), "history_count": len(history),
                "t_plus_one_incompatible_count": same_day_count,
                "errors": errors, "warnings": warnings,
                "cutover_eligible": not errors and not warnings,
                "migration_performed": False, "production_cutover_performed": False}
