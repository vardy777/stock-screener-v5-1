from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from v5.task_runner import run
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("task",choices=["morning_pool","morning_push","paper_sell","feature_freeze","confirmation","confirmation_push","paper_buy","health_check","maintenance"]);a=p.parse_args();r=run(ROOT/"v5/data",a.task,failure_alert_env=ROOT/"v5/.env");print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if r["passed"] else 3)
