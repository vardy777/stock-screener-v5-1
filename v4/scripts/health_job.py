#!/usr/bin/env python
"""V4-owned production entrypoint for strict capture health."""
import sys
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/"phase1"))
from phase1.scripts.verify_capture_health import main as health_main

def main():
    day=date.today().isoformat()
    # V4 notification ownership is retired.  Keep this legacy audit local
    # while the remaining paper ledger is migrated; it must never alert users.
    sys.argv=[sys.argv[0],"--trade-date",day,"--sessions","signal,buy"]
    return health_main()

if __name__=="__main__": raise SystemExit(main())
