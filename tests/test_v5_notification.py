import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from v5.core import CHINA_TZ,ContractViolation
from v5.notification import build_payload,send
def facts(root):
    day="2026-08-14";(root/"acquisition"/day).mkdir(parents=True);(root/"morning_pools"/day).mkdir(parents=True);(root/"confirmations"/day).mkdir(parents=True)
    (root/"acquisition"/day/"a.json").write_text(json.dumps({"accepted":True}),encoding="utf-8")
    candidate={"name":"测试","code":"000001","rank":1,"change_pct":2.3,"reasons":["可交易"],"risks":["隔夜风险"]}
    (root/"morning_pools"/day/"m.json").write_text(json.dumps({"pool_id":"v5mp1-test","snapshot_id":"ms1-a","candidates":[candidate]}),encoding="utf-8")
    (root/"confirmations"/day/"c.json").write_text(json.dumps({"confirmation_id":"v5cd1-test","morning_pool_id":"v5mp1-test","snapshot_id":"ms1-b","candidates":[candidate]}),encoding="utf-8");return day
def test_payload_and_dashboard_share_final_v5_entity():
    with TemporaryDirectory() as d:
        root=Path(d);day=facts(root);assert build_payload(root,day,"morning")["parent_entity_id"]=="v5mp1-test";assert build_payload(root,day,"confirmation")["parent_entity_id"]=="v5cd1-test"
def test_failed_gate_never_sends_and_accepted_receipt_is_idempotent():
    with TemporaryDirectory() as d:
        root=Path(d);day=facts(root);env=root/".env";env.write_text("PUSHPLUS_TOKEN=secret",encoding="utf-8");calls=[]
        receipt=send(root,day,"morning",env,transport=lambda:(calls.append(1) or {"code":200}));assert receipt["outcome"]=="ACCEPTED" and len(calls)==1;assert send(root,day,"morning",env,transport=lambda:calls.append(2))["outcome"]=="ACCEPTED" and len(calls)==1
        (root/"acquisition"/day/"z.json").write_text(json.dumps({"accepted":False}),encoding="utf-8")
        with pytest.raises(ContractViolation):build_payload(root,day,"confirmation")
def test_v5_notification_entrypoint_never_reads_v4_configuration():
    text=(Path(__file__).resolve().parents[1]/"v5/scripts/v5_push_job.py").read_text(encoding="utf-8")
    assert 'ROOT/"v5/.env"' in text and 'ROOT/"v4/.env"' not in text
