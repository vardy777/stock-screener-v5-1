"""Legacy frame capture compatibility; V4 core uses MarketDataGateway only."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Optional

import pandas as pd

from v4.execution import CHINA_TZ, TradingClock
from v4.market_contracts import (
    ContractViolation,
    EvidenceCohort,
    MarketSnapshotV1,
    QuoteV1,
)


ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_ROOT = ROOT / "phase1" / "data" / "execution_snapshots"


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _quality_report_path(current: datetime, cohort: EvidenceCohort, session: str) -> Path:
    return (
        SNAPSHOT_ROOT / "quality" / cohort.value / session
        / f"{current:%Y-%m-%d_%H%M%S}.json"
    )


def build_daily_quality_report(
    trade_date: str, *, root: Optional[Path] = None
) -> dict:
    """Aggregate immutable capture reports without merging evidence cohorts."""

    datetime.fromisoformat(trade_date)  # validates YYYY-MM-DD-compatible input
    base = Path(root or SNAPSHOT_ROOT)
    cohorts = {}
    for cohort in EvidenceCohort:
        entries = []
        reasons: dict[str, int] = {}
        for path in sorted((base / "quality" / cohort.value).glob(
            f"*/{trade_date}_*.json"
        )):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                item = {
                    "session": path.parent.name,
                    "quality": {"accepted": False, "reasons": ["invalid_report"]},
                }
            entries.append(item)
            for reason in item.get("quality", {}).get("reasons", []):
                reasons[str(reason)] = reasons.get(str(reason), 0) + 1
            for reason, count in item.get("rejected_rows", {}).items():
                reasons[str(reason)] = reasons.get(str(reason), 0) + int(count)
        cohorts[cohort.value] = {
            "captures": len(entries),
            "accepted": sum(
                bool(item.get("quality", {}).get("accepted")) for item in entries
            ),
            "rejected": sum(
                not bool(item.get("quality", {}).get("accepted")) for item in entries
            ),
            "reasons": reasons,
            "sessions": entries,
        }
    report = {
        "report_version": "daily-snapshot-quality-v1",
        "trade_date": trade_date,
        "generated_at": TradingClock.now().isoformat(timespec="seconds"),
        "cohorts_merged": False,
        "cohorts": cohorts,
    }
    _atomic_json(base / "quality" / "daily" / f"{trade_date}.json", report)
    return report


def _row_to_quote(row: dict, current: datetime) -> QuoteV1:
    quote_time = row.get("exchange_time") or row.get("quote_time")
    received_at = row.get("received_at") or current.isoformat()
    provider_time = row.get("provider_time") or quote_time
    price = row.get("price")
    return QuoteV1.from_mapping({
        "code": str(row.get("code", "")).zfill(6),
        "name": row.get("name"),
        "trade_date": row.get("trade_date") or current.date().isoformat(),
        "exchange_time": quote_time,
        "provider_time": provider_time,
        "received_at": received_at,
        "last_price": price,
        "previous_close": row.get("prev_close", price),
        "bid1": row.get("bid1", 0.0),
        "bid1_volume": row.get("bid1_volume", row.get("bid1_vol", 0)),
        "ask1": row.get("ask1", 0.0),
        "ask1_volume": row.get("ask1_volume", row.get("ask1_vol", 0)),
        "volume": row.get("volume", 0),
        "amount": row.get("amount", 0.0),
        "halted": row.get("halted", False),
        "limit_up": row.get("limit_up", False),
        "limit_down": row.get("limit_down", False),
        "provider": row.get("provider", "legacy_v4_adapter"),
    })


def capture_frame(
    frame: pd.DataFrame,
    session: str,
    *,
    now: Optional[datetime] = None,
    expected_codes=None,
    minimum_coverage: float = 0.95,
    capture_metadata: Optional[dict] = None,
    require_order_book: bool = False,
    capture_role: str = "strict_probe",
    evidence_cohort: str = "strict",
) -> Optional[Path]:
    """Validate and save a snapshot under ``strict/`` or ``paper_only/``.

    Rejected in-window captures write only a quality report.  They never write
    a CSV that could later be mistaken for accepted evidence.
    """

    if session not in {"buy", "sell"}:
        return None
    try:
        cohort = EvidenceCohort(evidence_cohort)
    except ValueError as exc:
        raise ValueError("evidence_cohort must be strict or paper_only") from exc
    current = now or TradingClock.now()
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(CHINA_TZ)
    status = TradingClock.action_status(session, now=current)
    if not status.allowed:
        return None

    expected = (
        {str(code).strip().zfill(6) for code in expected_codes if str(code).strip()}
        if expected_codes is not None else set()
    )
    batch_started = (
        (capture_metadata or {}).get("started_at")
        or getattr(frame, "attrs", {}).get("batch_started_at")
        or current.isoformat()
    )
    batch_completed = (
        (capture_metadata or {}).get("completed_at")
        or getattr(frame, "attrs", {}).get("batch_completed_at")
        or current.isoformat()
    )
    rejected: dict[str, int] = {}
    quotes: list[QuoteV1] = []
    source_rows = 0
    if frame is not None and not frame.empty:
        for raw in frame.to_dict(orient="records"):
            source_rows += 1
            code = str(raw.get("code", "")).strip().zfill(6)
            if expected and code not in expected:
                rejected["outside_expected_universe"] = rejected.get(
                    "outside_expected_universe", 0
                ) + 1
                continue
            if bool(raw.get("is_mock", False)):
                rejected["mock_quote"] = rejected.get("mock_quote", 0) + 1
                continue
            quote_time = raw.get("exchange_time") or raw.get("quote_time")
            if not TradingClock.quote_is_fresh(quote_time, now=current):
                rejected["non_fresh_quote"] = rejected.get("non_fresh_quote", 0) + 1
                continue
            name = str(raw.get("name", ""))
            if not name or "ST" in name.upper() or "退" in name:
                rejected["ineligible_name"] = rejected.get("ineligible_name", 0) + 1
                continue
            try:
                quotes.append(_row_to_quote(raw, current))
            except ContractViolation as exc:
                key = f"contract:{str(exc).split(':', 1)[0]}"
                rejected[key] = rejected.get(key, 0) + 1

    try:
        snapshot = MarketSnapshotV1.build(
            trade_date=current.date().isoformat(),
            session=session,
            batch_started_at=batch_started,
            batch_completed_at=batch_completed,
            quotes=quotes,
            expected_codes=len(expected) if expected else len({q.code for q in quotes}),
            cohort=cohort,
            minimum_coverage=minimum_coverage,
            require_order_book=require_order_book,
        )
        quality = snapshot.quality.to_dict()
    except ContractViolation as exc:
        quality = {
            "schema_version": "snapshot-quality-v1",
            "cohort": cohort.value,
            "accepted": False,
            "reasons": ["snapshot_contract_violation"],
            "detail": str(exc),
            "expected_codes": len(expected),
            "valid_codes": len({q.code for q in quotes}),
            "coverage": 0.0,
        }
        snapshot = None

    report = {
        "report_version": "capture-quality-report-v1",
        "session": session,
        "trade_date": current.date().isoformat(),
        "captured_at": current.isoformat(timespec="seconds"),
        "capture_role": str(capture_role),
        "source_rows": source_rows,
        "rejected_rows": rejected,
        "quality": quality,
        "fetch": capture_metadata or {},
    }
    report_path = _quality_report_path(current, cohort, session)
    _atomic_json(report_path, report)
    if snapshot is None or not snapshot.quality.accepted:
        return None

    rows = []
    by_code = {str(row.get("code", "")).strip().zfill(6): row for row in (
        frame.to_dict(orient="records") if frame is not None else []
    )}
    price_column = "ask1" if session == "buy" else "bid1"
    volume_column = "ask1_volume" if session == "buy" else "bid1_volume"
    for quote in snapshot.quotes:
        raw = by_code[quote.code]
        row = dict(raw)
        row["code"] = quote.code
        row["last_price"] = quote.last_price
        row["price"] = float(raw.get(price_column, 0)) if require_order_book else quote.last_price
        row["execution_price_source"] = price_column if require_order_book else "last_price"
        row["execution_queue_volume"] = int(raw.get(volume_column, 0)) if require_order_book else 0
        row["order_book_verified"] = bool(require_order_book)
        row["captured_at"] = current.isoformat(timespec="seconds")
        row["session"] = session
        row["is_mock"] = False
        row["quote_is_fresh"] = True
        row["window_valid"] = True
        row["capture_role"] = str(capture_role)
        row["evidence_cohort"] = cohort.value
        rows.append(row)
    saved = pd.DataFrame(rows).drop_duplicates("code", keep="last")
    output_dir = SNAPSHOT_ROOT / cohort.value / session
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{current:%Y-%m-%d_%H%M%S}.csv"
    temporary = output.with_suffix(output.suffix + ".tmp")
    saved.to_csv(temporary, index=False)
    temporary.replace(output)
    data_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
    universe_sha256 = hashlib.sha256(
        "\n".join(sorted(expected)).encode("utf-8")
    ).hexdigest() if expected else hashlib.sha256(
        "\n".join(sorted({q.code for q in quotes})).encode("utf-8")
    ).hexdigest()
    manifest = {
        "contract_version": "strict-execution-snapshot-v3"
        if cohort == EvidenceCohort.STRICT else "paper-execution-snapshot-v1",
        "market_snapshot_version": snapshot.schema_version,
        "quality_contract_version": snapshot.quality.schema_version,
        "evidence_cohort": cohort.value,
        "data_file": output.name,
        "data_sha256": data_sha256,
        "expected_universe_sha256": universe_sha256,
        "session": session,
        "captured_at": current.isoformat(timespec="seconds"),
        "batch_started_at": snapshot.batch_started_at,
        "batch_completed_at": snapshot.batch_completed_at,
        "expected_codes": len(expected) if expected else len(snapshot.quotes),
        "valid_rows": int(len(saved)),
        "coverage": float(snapshot.quality.coverage),
        "minimum_coverage": float(minimum_coverage),
        "causal_quote_time_required": True,
        "order_book_required": bool(require_order_book),
        "order_book_verified_rows": int(saved["order_book_verified"].sum()),
        "window_valid": True,
        "capture_role": str(capture_role),
        "quality_report": str(report_path.relative_to(SNAPSHOT_ROOT)),
        "quality": snapshot.quality.to_dict(),
    }
    if capture_metadata:
        manifest["fetch"] = capture_metadata
    _atomic_json(output.with_suffix(output.suffix + ".meta.json"), manifest)
    return output
