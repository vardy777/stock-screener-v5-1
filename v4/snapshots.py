"""Exact execution-window snapshot collection piggybacking on existing jobs."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Optional

import pandas as pd

from .execution import CHINA_TZ, TradingClock


ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_ROOT = ROOT / "phase1" / "data" / "execution_snapshots"


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
) -> Optional[Path]:
    """Save non-mock quotes only inside the corresponding execution window."""

    if session not in {"buy", "sell"}:
        return None
    current = now or TradingClock.now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=CHINA_TZ)
    else:
        current = current.astimezone(CHINA_TZ)
    status = TradingClock.action_status(session, now=current)
    if not status.allowed or frame is None or frame.empty:
        return None
    snapshot = frame.copy()
    if not {"code", "name", "price", "quote_time"}.issubset(snapshot.columns):
        return None
    snapshot["code"] = (
        snapshot["code"].astype(str).str.extract(r"(\d+)", expand=False).str.zfill(6)
    )
    expected = (
        {str(code).strip().zfill(6) for code in expected_codes}
        if expected_codes is not None
        else set()
    )
    if expected:
        snapshot = snapshot[snapshot["code"].isin(expected)]
    snapshot["price"] = pd.to_numeric(snapshot["price"], errors="coerce")
    snapshot["last_price"] = snapshot["price"]
    snapshot["order_book_verified"] = False
    if require_order_book:
        price_column = "ask1" if session == "buy" else "bid1"
        volume_column = "ask1_volume" if session == "buy" else "bid1_volume"
        if not {price_column, volume_column}.issubset(snapshot.columns):
            return None
        execution_price = pd.to_numeric(snapshot[price_column], errors="coerce")
        queue_volume = pd.to_numeric(snapshot[volume_column], errors="coerce")
        snapshot = snapshot[execution_price.gt(0) & queue_volume.gt(0)].copy()
        snapshot["price"] = execution_price.loc[snapshot.index]
        snapshot["execution_price_source"] = price_column
        snapshot["execution_queue_volume"] = queue_volume.loc[snapshot.index].astype(int)
        snapshot["order_book_verified"] = True
    else:
        snapshot["execution_price_source"] = "last_price"
        snapshot["execution_queue_volume"] = 0
    snapshot = snapshot[pd.to_numeric(snapshot["price"], errors="coerce") > 0]
    if "is_mock" in snapshot.columns:
        mock = (
            snapshot["is_mock"]
            .astype(str)
            .str.strip()
            .str.lower()
            .isin({"1", "true", "yes"})
        )
        snapshot = snapshot[~mock]
    fresh = snapshot["quote_time"].map(
        lambda value: TradingClock.quote_is_fresh(value, now=current)
    )
    snapshot = snapshot[fresh]
    if snapshot.empty:
        return None
    if "name" in snapshot.columns:
        snapshot = snapshot[~snapshot["name"].astype(str).str.contains("ST|退", na=False)]
    if snapshot.empty:
        return None
    snapshot = snapshot.drop_duplicates("code", keep="last").reset_index(drop=True)
    coverage = len(snapshot) / len(expected) if expected else 1.0
    if expected and coverage < minimum_coverage:
        return None
    snapshot["captured_at"] = current.isoformat(timespec="seconds")
    snapshot["session"] = session
    snapshot["is_mock"] = False
    snapshot["quote_is_fresh"] = True
    snapshot["window_valid"] = True
    snapshot["capture_role"] = str(capture_role)
    output_dir = SNAPSHOT_ROOT / session
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{current:%Y-%m-%d_%H%M%S}.csv"
    temporary = output.with_suffix(output.suffix + ".tmp")
    snapshot.to_csv(temporary, index=False)
    temporary.replace(output)
    data_sha256 = hashlib.sha256(output.read_bytes()).hexdigest()
    universe_sha256 = hashlib.sha256(
        "\n".join(sorted(expected)).encode("utf-8")
    ).hexdigest() if expected else ""
    manifest = {
        "contract_version": "strict-execution-snapshot-v2",
        "data_file": output.name,
        "data_sha256": data_sha256,
        "expected_universe_sha256": universe_sha256,
        "session": session,
        "captured_at": current.isoformat(timespec="seconds"),
        "expected_codes": len(expected) if expected else None,
        "valid_rows": int(len(snapshot)),
        "coverage": float(coverage),
        "minimum_coverage": float(minimum_coverage),
        "causal_quote_time_required": True,
        "order_book_required": bool(require_order_book),
        "order_book_verified_rows": int(snapshot["order_book_verified"].sum()),
        "window_valid": True,
        "capture_role": str(capture_role),
    }
    if capture_metadata:
        manifest["fetch"] = capture_metadata
    manifest_path = output.with_suffix(output.suffix + ".meta.json")
    manifest_temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    manifest_temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest_temporary.replace(manifest_path)
    return output
