import json
from datetime import datetime,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from v5.core import CHINA_TZ
from v5.fact_reader import latest
from v5.lineage_acceptance import audit
from v5.market_state import MarketStateV1
from v5.decision_flow import MorningPoolV5,ConfirmationV5
from v5.market_snapshot import QuoteV1,MarketSnapshotV1
from v5.contracts import AcquisitionSessionV1
from v5.storage import V5FactStore
from v5.shadow_schedule import ShadowScheduler

NOW=datetime(2026,8,14,9,25,tzinfo=CHINA_TZ)
def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding="utf-8")
def test_latest_uses_entity_time_not_content_hash_filename():
    with TemporaryDirectory() as d:
        root=Path(d);write(root/"morning_pools/2026-08-14/z.json",{"created_at":NOW.isoformat(),"value":"old"});write(root/"morning_pools/2026-08-14/a.json",{"created_at":(NOW+timedelta(minutes=1)).isoformat(),"value":"new"});assert latest(root,"morning_pools","2026-08-14")["value"]=="new"
def test_daily_lineage_acceptance_proves_snapshot_decision_and_notification_chain():
    with TemporaryDirectory() as d:
        root=Path(d);day="2026-08-14"
        def snapshot(at,session,provider):
            quote=QuoteV1.from_mapping({"code":"000001","name":"test","trade_date":day,"exchange_time":at-timedelta(seconds=1),"provider_time":at-timedelta(seconds=1),"received_at":at,"last_price":10.1,"previous_close":10,"open_price":10,"high_price":10.2,"low_price":9.9,"bid1":10.09,"bid1_volume":10000,"ask1":10.11,"ask1_volume":10000,"volume":100000,"amount":1000000,"halted":False,"limit_up":False,"limit_down":False,"provider":provider})
            return MarketSnapshotV1.build(trade_date=day,session=session,batch_started_at=at-timedelta(seconds=2),batch_completed_at=at,quotes=[quote],expected_codes=1)
        morning_at=NOW;signal_at=NOW.replace(hour=14,minute=49);morning_snap=snapshot(morning_at,"morning","sina");signal_snap=snapshot(signal_at,"signal","eastmoney");morning=morning_snap.snapshot_id;signal=signal_snap.snapshot_id;store=V5FactStore(root);store.save_snapshot(morning_snap);store.save_snapshot(signal_snap)
        m_acq=AcquisitionSessionV1.build(trade_date=day,stage="morning",requested_at=morning_at,expected_codes=1,selected_snapshot_id=morning,accepted=True,source_attempts=[{"source":"sina","snapshot_id":morning,"complete":True}]);s_acq=AcquisitionSessionV1.build(trade_date=day,stage="signal",requested_at=signal_at,expected_codes=1,selected_snapshot_id=signal,accepted=True,source_attempts=[{"source":"eastmoney","snapshot_id":signal,"complete":True}]);store.save_session(m_acq);store.save_session(s_acq)
        candidate={"code":"000001","name":"test","rank":1,"change_pct":1,"reasons":[],"risks":[]}
        morning_state=MarketStateV1(day,morning,1,1,0,0,0,0,0,1e8,.01,1,0,"STRONG",True,());signal_state=MarketStateV1(day,signal,1,1,0,0,0,0,0,1e8,.01,1,0,"STRONG",True,());write(root/f"market_states/{day}/{morning_state.market_state_id}.json",morning_state.to_dict());write(root/f"market_states/{day}/{signal_state.market_state_id}.json",signal_state.to_dict())
        pool_entity=MorningPoolV5(day,NOW.isoformat(),"funnel1-morning",morning,morning_state.market_state_id,(candidate,));pool=pool_entity.pool_id
        confirmation_entity=ConfirmationV5(day,NOW.replace(hour=14,minute=50).isoformat(),pool,"funnel1-confirm",signal,signal_state.market_state_id,(candidate,),(),"BUY_CANDIDATE");confirmation=confirmation_entity.confirmation_id
        write(root/f"morning_pools/{day}/p.json",pool_entity.to_dict())
        write(root/f"confirmations/{day}/c.json",confirmation_entity.to_dict())
        write(root/f"frozen/{day}/signal.json",{"snapshot_id":signal,"acquisition_session_id":s_acq.session_id})
        from v5.index_capture import capture as capture_index
        from v5.index_benchmark import source_observation
        class IndexSource:
            def __init__(self,name,price):self.name=name;self.price=price
            def capture(self,now):return source_observation(observed_at=now.isoformat(),previous_close=4000,last_price=self.price,provider=self.name,source_snapshot_id=f"response-{self.name}")
        capture_index(root,now=signal_at,sources=(IndexSource("index_a",3980),IndexSource("index_b",3979)))
        from v5.notification import build_payload
        scheduler=ShadowScheduler(root)
        for stage,parent,run_at in (("morning",pool,morning_at+timedelta(seconds=30)),("confirmation",confirmation,signal_at+timedelta(minutes=1,seconds=30))):
            payload=build_payload(root,day,stage,as_of=run_at)
            scheduler.record(f"{stage}_push",day,"SUCCESS",run_at,{"parent_entity_id":parent,"payload_sha256":payload["payload_sha256"]})
            write(root/f"notifications/{day}/{stage}.json",{"outcome":"ACCEPTED","response_code":200,"parent_entity_id":parent,"payload_sha256":payload["payload_sha256"]})
        assert audit(root,day,as_of=signal_at+timedelta(minutes=4))["passed"]
        row=json.loads((root/f"confirmations/{day}/c.json").read_text());row["snapshot_id"]="ms1-wrong";write(root/f"confirmations/{day}/c.json",row);assert not audit(root,day)["passed"]

def test_daily_lineage_rejects_tampered_acquisition_hash_before_projection(tmp_path):
    day="2026-08-14";directory=tmp_path/"acquisition"/day;directory.mkdir(parents=True)
    row={"schema_version":"v5-acquisition-session-v1","trade_date":day,"stage":"morning","requested_at":NOW.isoformat(),"expected_codes":1,"selected_snapshot_id":"ms1-test","accepted":True,"source_attempts":[{"source":"sina"}],"session_id":"acq1-forged"}
    write(directory/"m.json",row)
    report=audit(tmp_path,day);assert not report["passed"] and report["checks"].get("audit_completed") is False
