#!/usr/bin/env python
"""Build a non-applicable P3/P4/P5 cutover plan from explicit read-only inputs."""
import argparse,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from v4.cutover_readiness import build_cutover_readiness

def load(path):
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError): return {}

def main():
    for stream in (sys.stdout,sys.stderr):
        reconfigure=getattr(stream,"reconfigure",None)
        if reconfigure is not None: reconfigure(encoding="utf-8",errors="backslashreplace")
    parser=argparse.ArgumentParser(); parser.add_argument("--live-report",type=Path,required=True)
    parser.add_argument("--legacy-account",type=Path,required=True); parser.add_argument("--task-inventory",type=Path,required=True)
    parser.add_argument("--backup-report",type=Path,required=True); parser.add_argument("--writer-inventory",type=Path,required=True); args=parser.parse_args()
    tasks=load(args.task_inventory); tasks=tasks if isinstance(tasks,list) else tasks.get("tasks",[])
    report=build_cutover_readiness(project_root=ROOT,live_acceptance=load(args.live_report),legacy_account_path=args.legacy_account,
        installed_tasks=tasks,backup_verification=load(args.backup_report),writers=load(args.writer_inventory).get("writers",[]))
    print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if report["ready"] else 1
if __name__=="__main__": raise SystemExit(main())
