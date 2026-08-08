#!/usr/bin/env python
"""Validate one real P2 session without mutating project or trading state."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from v4.p2_acceptance import validate_p2_session


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trade-date", default=date.today().isoformat())
    args = parser.parse_args()
    report = validate_p2_session(
        args.trade_date,
        journal_dir=ROOT / "v4" / "data" / "candidate_journal",
        log_dir=ROOT / "phase1" / "data" / "logs",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
