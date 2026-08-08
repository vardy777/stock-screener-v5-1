#!/usr/bin/env python
"""Scheduled V4 research paper-account execution (never a broker order)."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from v4.simulation import SimulationEngine


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("buy", "sell"))
    args = parser.parse_args()
    engine = SimulationEngine()
    engine.load_state()
    if args.mode == "buy":
        result = engine.execute_buy(
            refresh_candidates=False,
            paper_observation=True,
        )
    else:
        result = engine.execute_sell()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
