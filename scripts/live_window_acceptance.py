#!/usr/bin/env python
"""Generate a read-only real-window acceptance report for one trade date."""
import argparse,json,sys
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from v4.live_window_acceptance import derive_project_evidence,validate_live_window_chain,write_acceptance_report,write_evidence_once

def main():
    for stream in (sys.stdout,sys.stderr):
        reconfigure=getattr(stream,"reconfigure",None)
        if reconfigure is not None: reconfigure(encoding="utf-8",errors="backslashreplace")
    parser=argparse.ArgumentParser(); parser.add_argument("--trade-date",default=date.today().isoformat())
    parser.add_argument("--evidence-dir",type=Path,default=ROOT/"v4"/"data"/"live_window_evidence")
    parser.add_argument("--output",type=Path); parser.add_argument("--derive-project",action="store_true")
    parser.add_argument("--next-session-date"); args=parser.parse_args()
    if args.derive_project:
        if not args.next_session_date: parser.error("--next-session-date is required with --derive-project")
        values=derive_project_evidence(args.trade_date,args.next_session_date,journal_dir=ROOT/"v4"/"data"/"candidate_journal",
            log_dir=ROOT/"phase1"/"data"/"logs",snapshot_root=ROOT/"phase1"/"data"/"execution_snapshots")
        target=args.evidence_dir/args.trade_date; target.mkdir(parents=True,exist_ok=True)
        for name,value in values.items():
            if value.get("status") != "PASSED": continue
            path=target/f"{name}.json"
            write_evidence_once(value,path)
    report=validate_live_window_chain(args.trade_date,args.evidence_dir)
    if args.output: write_acceptance_report(report,args.output)
    print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if report["passed"] else 1
if __name__=="__main__": raise SystemExit(main())
