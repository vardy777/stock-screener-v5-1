import json
from datetime import datetime,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from v5.core import CHINA_TZ
from v5.fact_reader import latest
from v5.lineage_acceptance import audit
from v5.market_state import MarketStateV1

NOW=datetime(2026,8,14,9,25,tzinfo=CHINA_TZ)
def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding="utf-8")
def test_latest_uses_entity_time_not_content_hash_filename():
    with TemporaryDirectory() as d:
        root=Path(d);write(root/"morning_pools/2026-08-14/z.json",{"created_at":NOW.isoformat(),"value":"old"});write(root/"morning_pools/2026-08-14/a.json",{"created_at":(NOW+timedelta(minutes=1)).isoformat(),"value":"new"});assert latest(root,"morning_pools","2026-08-14")["value"]=="new"
def test_daily_lineage_acceptance_proves_snapshot_decision_and_notification_chain():
    with TemporaryDirectory() as d:
        root=Path(d);day="2026-08-14";morning="ms1-morning";signal="ms1-signal";pool="v5mp1-pool";confirmation="v5cd1-decision"
        write(root/f"snapshots/{day}/{morning}.json",{});write(root/f"snapshots/{day}/{signal}.json",{})
        write(root/f"acquisition/{day}/m.json",{"stage":"morning","requested_at":NOW.isoformat(),"accepted":True,"session_id":"acq1-m","selected_snapshot_id":morning})
        write(root/f"acquisition/{day}/s.json",{"stage":"signal","requested_at":NOW.replace(hour=14,minute=49).isoformat(),"accepted":True,"session_id":"acq1-s","selected_snapshot_id":signal})
        candidate={"code":"000001","name":"test","rank":1,"change_pct":1,"reasons":[],"risks":[]}
        morning_state=MarketStateV1(day,morning,1,1,0,0,0,0,0,1e8,.01,1,0,"STRONG",True,());signal_state=MarketStateV1(day,signal,1,1,0,0,0,0,0,1e8,.01,1,0,"STRONG",True,());write(root/f"market_states/{day}/{morning_state.market_state_id}.json",morning_state.to_dict());write(root/f"market_states/{day}/{signal_state.market_state_id}.json",signal_state.to_dict())
        write(root/f"morning_pools/{day}/p.json",{"pool_id":pool,"created_at":NOW.isoformat(),"snapshot_id":morning,"market_state_id":morning_state.market_state_id,"candidates":[candidate]})
        write(root/f"confirmations/{day}/c.json",{"confirmation_id":confirmation,"decided_at":NOW.replace(hour=14,minute=50).isoformat(),"morning_pool_id":pool,"snapshot_id":signal,"market_state_id":signal_state.market_state_id,"candidates":[candidate]})
        write(root/f"frozen/{day}/signal.json",{"snapshot_id":signal,"acquisition_session_id":"acq1-s"})
        from v5.notification import build_payload
        for stage,parent in (("morning",pool),("confirmation",confirmation)):
            payload=build_payload(root,day,stage);write(root/f"notifications/{day}/{stage}.json",{"outcome":"ACCEPTED","response_code":200,"parent_entity_id":parent,"payload_sha256":payload["payload_sha256"]})
        assert audit(root,day)["passed"]
        row=json.loads((root/f"confirmations/{day}/c.json").read_text());row["snapshot_id"]="ms1-wrong";write(root/f"confirmations/{day}/c.json",row);assert not audit(root,day)["passed"]
