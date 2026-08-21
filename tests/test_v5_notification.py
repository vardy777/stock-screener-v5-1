import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from v5.core import CHINA_TZ,ContractViolation
from v5.notification import build_payload,send
from v5.market_state import MarketStateV1
from v5.decision_flow import MorningPoolV5,ConfirmationV5
def facts(root):
    day="2026-08-14";(root/"acquisition"/day).mkdir(parents=True);(root/"morning_pools"/day).mkdir(parents=True);(root/"confirmations"/day).mkdir(parents=True);(root/"market_states"/day).mkdir(parents=True)
    (root/"acquisition"/day/"a.json").write_text(json.dumps({"accepted":True,"stage":"morning","requested_at":f"{day}T09:25:00+08:00","selected_snapshot_id":"ms1-a"}),encoding="utf-8")
    (root/"acquisition"/day/"b.json").write_text(json.dumps({"accepted":True,"stage":"signal","requested_at":f"{day}T14:49:00+08:00","selected_snapshot_id":"ms1-b"}),encoding="utf-8")
    candidate={"name":"测试","code":"000001","rank":1,"change_pct":2.3,"reasons":["可交易"],"risks":["隔夜风险"]}
    morning_state=MarketStateV1(day,"ms1-a",4900,3000,1900,0,0,0,0,1e12,.01,3000/4900,0,"STRONG",True,());signal_state=MarketStateV1(day,"ms1-b",4900,3000,1900,0,0,0,0,1e12,.01,3000/4900,0,"STRONG",True,())
    pool=MorningPoolV5(day,f"{day}T09:25:00+08:00","funnel1-test","ms1-a",morning_state.market_state_id,(candidate,));pool_raw=pool.to_dict()
    confirmation=ConfirmationV5(day,f"{day}T14:50:00+08:00",pool.pool_id,"funnel1-confirm","ms1-b",signal_state.market_state_id,(candidate,),(),"BUY_CANDIDATE");confirmation_raw=confirmation.to_dict()
    (root/"morning_pools"/day/"m.json").write_text(json.dumps(pool_raw),encoding="utf-8")
    (root/"confirmations"/day/"c.json").write_text(json.dumps(confirmation_raw),encoding="utf-8");(root/"market_states"/day/f"{morning_state.market_state_id}.json").write_text(json.dumps(morning_state.to_dict()),encoding="utf-8");(root/"market_states"/day/f"{signal_state.market_state_id}.json").write_text(json.dumps(signal_state.to_dict()),encoding="utf-8");return day
def test_payload_and_dashboard_share_final_v5_entity():
    with TemporaryDirectory() as d:
        root=Path(d);day=facts(root);morning=build_payload(root,day,"morning");confirmation=build_payload(root,day,"confirmation");assert morning["parent_entity_id"].startswith("v5mp1-");assert confirmation["parent_entity_id"].startswith("v5cd1-");assert "早盘候选只观察" in morning["content"] and "不展示买价" in morning["content"];assert "本地严格模拟" in confirmation["content"] and "不预测卖价" in confirmation["content"] and "不连接券商" in confirmation["content"]
        assert morning["candidate_codes"]==confirmation["candidate_codes"]==["000001"]
        assert morning["candidate_count"]==confirmation["candidate_count"]==1
        assert morning["snapshot_id"]=="ms1-a" and confirmation["snapshot_id"]=="ms1-b"

def test_notification_projects_every_candidate_from_final_entity():
    with TemporaryDirectory() as d:
        root=Path(d);day=facts(root);path=root/"confirmations"/day/"c.json";entity=json.loads(path.read_text(encoding="utf-8"));base=entity["candidates"][0]
        entity["candidates"]=[dict(base,code=f"{index:06d}",rank=index) for index in range(1,6)];rebuilt=ConfirmationV5(entity["trade_date"],entity["decided_at"],entity["morning_pool_id"],entity["funnel_id"],entity["snapshot_id"],entity["market_state_id"],tuple(entity["candidates"]),tuple(entity["changes"]),entity["outcome"]);entity["confirmation_id"]=rebuilt.confirmation_id;path.write_text(json.dumps(entity),encoding="utf-8")
        payload=build_payload(root,day,"confirmation")
        assert payload["candidate_codes"]==[f"{index:06d}" for index in range(1,6)] and payload["candidate_count"]==5
        assert all(code in payload["content"] for code in payload["candidate_codes"])
def test_failed_gate_never_sends_and_accepted_receipt_is_idempotent():
    with TemporaryDirectory() as d:
        root=Path(d);day=facts(root);env=root/".env";env.write_text("PUSHPLUS_TOKEN=secret",encoding="utf-8");calls=[]
        receipt=send(root,day,"morning",env,transport=lambda:(calls.append(1) or {"code":200}));assert receipt["outcome"]=="ACCEPTED" and len(calls)==1;assert send(root,day,"morning",env,transport=lambda:calls.append(2))["outcome"]=="ACCEPTED" and len(calls)==1
        (root/"acquisition"/day/"z.json").write_text(json.dumps({"accepted":False,"stage":"signal","requested_at":f"{day}T14:49:30+08:00"}),encoding="utf-8")
        with pytest.raises(ContractViolation):build_payload(root,day,"confirmation")
def test_v5_notification_entrypoint_never_reads_v4_configuration():
    text=(Path(__file__).resolve().parents[1]/"v5/scripts/v5_push_job.py").read_text(encoding="utf-8")
    assert 'from v5.task_runner import run' in text and 'ROOT/"v5/.env"' in text and 'ROOT/"v4/.env"' not in text
def test_rejected_push_attempt_is_audited_but_does_not_block_retry():
    with TemporaryDirectory() as d:
        root=Path(d);day=facts(root);env=root/".env";env.write_text("PUSHPLUS_TOKEN=secret",encoding="utf-8")
        with pytest.raises(RuntimeError):send(root,day,"morning",env,transport=lambda:{"code":500})
        assert not (root/"notifications"/day/"morning.json").exists() and len(list((root/"notification_attempts"/day/"morning").glob("*.json")))==1
        receipt=send(root,day,"morning",env,transport=lambda:{"code":200});assert receipt["outcome"]=="ACCEPTED" and (root/"notifications"/day/"morning.json").exists()

def test_payload_fails_closed_on_snapshot_lineage_mismatch_or_future_fact():
    with TemporaryDirectory() as d:
        root=Path(d);day=facts(root);now=datetime.fromisoformat(f"{day}T09:25:20+08:00")
        raw=json.loads((root/"morning_pools"/day/"m.json").read_text(encoding="utf-8"));raw["snapshot_id"]="ms1-wrong";(root/"morning_pools"/day/"m.json").write_text(json.dumps(raw),encoding="utf-8")
        with pytest.raises(ContractViolation,match="hash mismatch"):build_payload(root,day,"morning",as_of=now)
        raw["snapshot_id"]="ms1-a";raw["created_at"]=f"{day}T09:26:00+08:00";(root/"morning_pools"/day/"m.json").write_text(json.dumps(raw),encoding="utf-8")
        with pytest.raises(ContractViolation,match="causal"):build_payload(root,day,"morning",as_of=now)

def test_production_payload_rejects_missing_or_stale_snapshot_content():
    with TemporaryDirectory() as d:
        root=Path(d);day=facts(root);now=datetime.fromisoformat(f"{day}T09:25:20+08:00")
        with pytest.raises(ContractViolation,match="snapshot content missing"):build_payload(root,day,"morning",as_of=now)
        path=root/"snapshots"/day/"ms1-a.json";path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"quotes":[{"exchange_time":f"{day}T09:23:00+08:00","provider_time":f"{day}T09:23:00+08:00"}]}),encoding="utf-8")
        with pytest.raises(ContractViolation,match="snapshot stale"):build_payload(root,day,"morning",as_of=now)
        path.write_text(json.dumps({"quotes":[{"exchange_time":f"{day}T09:20:00+08:00","provider_time":f"{day}T09:24:30+08:00"}]}),encoding="utf-8")
        payload=build_payload(root,day,"morning",as_of=now);assert payload["maximum_quote_age_seconds"]==50

def test_concurrent_notification_delivery_sends_exactly_once():
    with TemporaryDirectory() as d:
        root=Path(d);day=facts(root);env=root/".env";env.write_text("PUSHPLUS_TOKEN=secret",encoding="utf-8");calls=[]
        def transport():calls.append(1);return {"code":200}
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:send(root,day,"morning",env,transport=transport),range(2)))
        assert len(calls)==1 and all(row["outcome"]=="ACCEPTED" for row in results)
