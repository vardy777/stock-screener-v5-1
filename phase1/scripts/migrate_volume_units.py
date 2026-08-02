#!/usr/bin/env python3
"""One-time, resumable conversion of the legacy Sina volume x100 bug."""

import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))

import pandas as pd

from overnight.archive_refresh import normalise_volume_to_shares, save_archive_atomic
from v4.execution import CHINA_TZ


def main() -> int:
    daily = BASE / "data" / "daily"
    marker = daily / ".volume_unit_contract.json"
    paths = sorted(daily.glob("*.csv"))
    reasons = {}
    examples = {}
    for index, path in enumerate(paths, start=1):
        try:
            frame = pd.read_csv(path, low_memory=False)
            before = float(pd.to_numeric(frame.get("volume"), errors="coerce").median())
            normalised, reason = normalise_volume_to_shares(frame)
            if reason == "converted":
                save_archive_atomic(normalised, path)
            after = float(
                pd.to_numeric(normalised.get("volume"), errors="coerce").median()
            )
            examples.setdefault(reason, {"code": path.stem, "before": before, "after": after})
        except Exception as exc:
            reason = f"exception:{type(exc).__name__}"
        reasons[reason] = reasons.get(reason, 0) + 1
        if index % 250 == 0 or index == len(paths):
            print(f"  volume migration: {index}/{len(paths)}", flush=True)

    unresolved = sum(
        count
        for reason, count in reasons.items()
        if reason not in {"converted", "already_shares"}
    )
    report = {
        "contract_version": "sina-volume-shares-v1",
        "completed_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
        "files_considered": len(paths),
        "reasons": reasons,
        "examples": examples,
        "volume_unit": "shares",
        "complete": bool(paths and unresolved == 0),
    }
    temporary = marker.with_suffix(marker.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(marker)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
