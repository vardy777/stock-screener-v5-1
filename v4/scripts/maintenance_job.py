#!/usr/bin/env python
"""V4-owned production entrypoint for next-session research preparation."""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/"phase1"))
from phase1.scripts.prepare_next_session import main as maintenance_main

def main(): return maintenance_main()

if __name__=="__main__": raise SystemExit(main())
