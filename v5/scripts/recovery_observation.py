from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from v5.recovery_observation import run
if __name__=="__main__":
 result=run(ROOT/"v5/data");print(json.dumps(result,ensure_ascii=False));raise SystemExit(0)
