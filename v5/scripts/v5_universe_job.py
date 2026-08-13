from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from v5.universe_refresh import refresh
if __name__=="__main__":
 result=refresh(ROOT/"v5/data");print(json.dumps(result,ensure_ascii=False))
