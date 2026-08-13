from datetime import datetime
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from v5.core import CHINA_TZ
from v5.jobs import produce
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("stage",choices=["morning","confirmation"]);args=parser.parse_args();print(json.dumps(produce(ROOT/"v5/data",args.stage,now=datetime.now(CHINA_TZ)),ensure_ascii=False))
