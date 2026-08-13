from datetime import datetime
from pathlib import Path
import argparse,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from v5.core import CHINA_TZ
from v5.notification import send
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("stage",choices=["morning","confirmation"]);parser.add_argument("--trade-date");args=parser.parse_args();day=args.trade_date or datetime.now(CHINA_TZ).date().isoformat();send(ROOT/"v5/data",day,args.stage,ROOT/"v4/.env")
