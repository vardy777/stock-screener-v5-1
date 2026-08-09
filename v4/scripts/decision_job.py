#!/usr/bin/env python
"""Candidate/decision producer, deliberately separate from push consumers."""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from v4.decision_production import P2DecisionProducer


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("morning", "confirmation"))
    args = parser.parse_args(argv)
    P2DecisionProducer().produce(args.stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
