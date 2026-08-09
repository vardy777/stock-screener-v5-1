#!/usr/bin/env python
"""Single read-only engineering acceptance command."""
from __future__ import annotations
import argparse,json,re,subprocess,sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from scripts.project_status import build_report
from v4.offline_rehearsal import successful_empty_cycle
from v4.cutover_rehearsal import full_frozen_rehearsal
from v4.operations_preflight import operational_preflight
from v4.production_architecture_audit import audit_production_architecture

def configure_console():
    for stream in (sys.stdout,sys.stderr):
        reconfigure=getattr(stream,"reconfigure",None)
        if reconfigure is not None: reconfigure(encoding="utf-8",errors="backslashreplace")

def secret_scan():
    findings=[]
    patterns=(re.compile(r"PUSHPLUS_TOKEN\s*=\s*[0-9a-fA-F]{32}"),
              re.compile(r'["\']token["\']\s*[:=]\s*["\'][0-9a-fA-F]{32}["\']'))
    for base in (ROOT/"v4",ROOT/"scripts",ROOT/"docs"):
        for path in base.rglob("*"):
            if not path.is_file() or path.name==".env" or path.suffix.lower() not in {".py",".md",".json",".ps1",".txt"}: continue
            try: text=path.read_text(encoding="utf-8")
            except (OSError,UnicodeError): continue
            if any(pattern.search(text) for pattern in patterns): findings.append(str(path.relative_to(ROOT)))
    return findings

def build(*,run_tests=False):
    project=build_report(); operations=operational_preflight(ROOT); rehearsal=successful_empty_cycle()
    architecture=audit_production_architecture(ROOT)
    cutover_rehearsal=full_frozen_rehearsal()
    tests={"run":False,"passed":None,"exit_code":None}
    if run_tests:
        result=subprocess.run([str(ROOT/".venv"/"Scripts"/"python.exe"),"-m","pytest","-q"],cwd=ROOT,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,shell=False,timeout=240)
        tests={"run":True,"passed":result.returncode==0,"exit_code":result.returncode}
    secrets=secret_scan(); checks={"project_consistency":project["ok"],"operations":operations["passed"],
        "frozen_rehearsal":rehearsal["passed"],"cutover_fault_matrix":cutover_rehearsal["passed"],
        "secret_scan":not secrets,"production_architecture":architecture["passed"],
        "tests":tests["passed"] is True}
    return {"schema_version":"offline-acceptance-report-v1","generated_at":datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "passed":all(checks.values()),"checks":checks,"project":project,"operations":operations,"rehearsal":rehearsal,
        "cutover_rehearsal":cutover_rehearsal,"production_architecture":architecture,
        "tests":tests,"secret_findings":secrets,"production_mutated":False}

def main():
    configure_console()
    parser=argparse.ArgumentParser(); parser.add_argument("--run-tests",action="store_true"); parser.add_argument("--output",type=Path); args=parser.parse_args()
    report=build(run_tests=args.run_tests)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if report["passed"] else 1
if __name__=="__main__": raise SystemExit(main())
