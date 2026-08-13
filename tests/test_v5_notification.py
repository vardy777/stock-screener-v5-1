import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from v5.core import CHINA_TZ,ContractViolation
from v5.notification import build_payload,send
def facts(root):
    day="2026-08-14";(root/"acquisition"/day).mkdir(parents=True);(root/"morning_pools"/day).mkdir(parents=True);(root/"confirmations"/day).mkdir(parents=True)
    (root/"acquisition"/day/"a.json").write_text(json.dumps({"accepted":True,"stage":"morning","requested_at":f"{day}T09:25:00+08:00","selected_snapshot_id":"ms1-a"}),encoding="utf-8")
    (root/"acquisition"/day/"b.json").write_text(json.dumps({"accepted":True,"stage":"signal","requested_at":f"{day}T14:49:00+08:00","selected_snapshot_id":"ms1-b"}),encoding="utf-8")
    candidate={"name":"测试","code":"000001","rank":1,"change_pct":2.3,"reasons":["可交易"],"risks":["隔夜风险"]}
    (root/"morning_pools"/day/"m.json").write_text(json.dumps({"pool_id":"v5mp1-test","created_at":f"{day}T09:25:00+08:00","snapshot_id":"ms1-a","candidates":[candidate]}),encoding="utf-8")
    (root/"confirmations"/day/"c.json").write_text(json.dumps({"confirmation_id":"v5cd1-test","decided_at":f"{day}T14:50:00+08:00","morning_pool_id":"v5mp1-test","snapshot_id":"ms1-b","candidates":[candidate]}),encoding="utf-8");return day
def test_payload_and_dashboard_share_final_v5_entity():
    with TemporaryDirectory() as d:
        root=Path(d);day=facts(root);morning=build_payload(root,day,"morning");confirmation=build_payload(root,day,"confirmation");assert morning["parent_entity_id"]=="v5mp1-test";assert confirmation["parent_entity_id"]=="v5cd1-test";assert "早盘候选只观察" in morning["content"] and "不展示买价" in morning["content"];assert "本地严格模拟" in confirmation["content"] and "不预测卖价" in confirmation["content"] and "不连接券商" in confirmation["content"]
def test_failed_gate_never_sends_and_accepted_receipt_is_idempotent():
    with TemporaryDirectory() as d:
        root=Path(d);day=facts(root);env=root/".env";env.write_text("PUSHPLUS_TOKEN=secret",encoding="utf-8");calls=[]
        receipt=send(root,day,"morning",env,transport=lambda:(calls.append(1) or {"code":200}));assert receipt["outcome"]=="ACCEPTED" and len(calls)==1;assert send(root,day,"morning",env,transport=lambda:calls.append(2))["outcome"]=="ACCEPTED" and len(calls)==1
        (root/"acquisition"/day/"z.json").write_text(json.dumps({"accepted":False,"stage":"signal","requested_at":f"{day}T14:49:30+08:00"}),encoding="utf-8")
        with pytest.raises(ContractViolation):build_payload(root,day,"confirmation")
def test_v5_notification_entrypoint_never_reads_v4_configuration():
    text=(Path(__file__).resolve().parents[1]/"v5/scripts/v5_push_job.py").read_text(encoding="utf-8")
    assert 'ROOT/"v5/.env"' in text and 'ROOT/"v4/.env"' not in text
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
        with pytest.raises(ContractViolation,match="lineage mismatch"):build_payload(root,day,"morning",as_of=now)
        raw["snapshot_id"]="ms1-a";raw["created_at"]=f"{day}T09:26:00+08:00";(root/"morning_pools"/day/"m.json").write_text(json.dumps(raw),encoding="utf-8")
        with pytest.raises(ContractViolation,match="causal"):build_payload(root,day,"morning",as_of=now)
