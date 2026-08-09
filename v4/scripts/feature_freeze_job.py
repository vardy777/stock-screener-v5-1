#!/usr/bin/env python
"""V4-owned production entrypoint for the strict 14:49 feature freeze."""
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/"phase1"))
from phase1.scripts.capture_signal_features import main as feature_main

def main(): return feature_main()

if __name__=="__main__": raise SystemExit(main())
