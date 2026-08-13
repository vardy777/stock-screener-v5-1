import json
import pytest
from datetime import datetime,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from v5.core import CHINA_TZ
from v5.sources import V5ReadOnlySources

DAY="2026-08-14"
MORNING=datetime(2026,8,14,9,25,tzinfo=CHINA_TZ)

def write(root,kind,name,row):
    path=Path(root)/kind/DAY/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(row),encoding="utf-8")

def acquisition(stage,at,snapshot):
    return {"trade_date":DAY,"stage":stage,"requested_at":at.isoformat(),"expected_codes":1,"selected_snapshot_id":snapshot,"accepted":True,"source_attempts":[{"source":stage,"coverage":1.0}]}

def test_dashboard_never_pairs_morning_pool_with_signal_acquisition():
    with TemporaryDirectory() as d:
        root=Path(d);write(root,"acquisition","m.json",acquisition("morning",MORNING,"ms1-morning"));write(root,"acquisition","s.json",acquisition("signal",MORNING.replace(hour=14,minute=49),"ms1-signal"));write(root,"morning_pools","m.json",{"trade_date":DAY,"created_at":MORNING.isoformat(),"funnel_id":"f1","snapshot_id":"ms1-morning","market_state_id":"state","candidates":[]})
        model=V5ReadOnlySources(root).build(DAY,as_of=MORNING.replace(hour=14,minute=49,second=30)).to_dict()
        assert model["today"]["snapshot_id"]=="ms1-morning" and model["today"]["source"]=="morning"

def test_dashboard_ignores_future_facts():
    with TemporaryDirectory() as d:
        root=Path(d);future=MORNING+timedelta(minutes=1);write(root,"acquisition","future.json",acquisition("morning",future,"ms1-future"));write(root,"morning_pools","future.json",{"trade_date":DAY,"created_at":future.isoformat(),"funnel_id":"f1","snapshot_id":"ms1-future","market_state_id":"state","candidates":[]})
        model=V5ReadOnlySources(root).build(DAY,as_of=MORNING).to_dict()
        assert model["today"]["data_quality"]=="unavailable" and model["today"]["snapshot_id"]==""

def test_dashboard_rejects_acquisition_snapshot_mismatch():
    with TemporaryDirectory() as d:
        root=Path(d);write(root,"acquisition","m.json",acquisition("morning",MORNING,"ms1-other"));write(root,"morning_pools","m.json",{"trade_date":DAY,"created_at":MORNING.isoformat(),"funnel_id":"f1","snapshot_id":"ms1-morning","market_state_id":"state","candidates":[]})
        with pytest.raises(ValueError,match="acquisition snapshot lineage mismatch"):
            V5ReadOnlySources(root).build(DAY,as_of=MORNING)

def test_dashboard_rejects_confirmation_from_other_mother_pool():
    with TemporaryDirectory() as d:
        root=Path(d);signal=MORNING.replace(hour=14,minute=49);decision=signal.replace(minute=50)
        write(root,"acquisition","m.json",acquisition("morning",MORNING,"ms1-morning"));write(root,"acquisition","s.json",acquisition("signal",signal,"ms1-signal"))
        write(root,"morning_pools","m.json",{"trade_date":DAY,"created_at":MORNING.isoformat(),"funnel_id":"f1","snapshot_id":"ms1-morning","market_state_id":"state-m","candidates":[]})
        write(root,"confirmations","c.json",{"trade_date":DAY,"decided_at":decision.isoformat(),"morning_pool_id":"v5mp1-other","funnel_id":"f2","snapshot_id":"ms1-signal","market_state_id":"state-s","candidates":[],"changes":[],"outcome":"EMPTY"})
        with pytest.raises(ValueError,match="mother-pool lineage mismatch"):
            V5ReadOnlySources(root).build(DAY,as_of=decision)
