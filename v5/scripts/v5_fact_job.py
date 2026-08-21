"""Compatibility CLI delegated to the only V5 business task runner."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from v5.task_runner import run
if __name__=="__main__":
 parser=argparse.ArgumentParser();parser.add_argument("stage",choices=["morning","confirmation"]);args=parser.parse_args();task={"morning":"morning_pool","confirmation":"confirmation"}[args.stage];result=run(ROOT/"v5/data",task,failure_alert_env=ROOT/"v5/.env");print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result["passed"] else 3)
