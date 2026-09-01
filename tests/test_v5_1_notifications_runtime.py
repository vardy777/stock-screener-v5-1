import json
from pathlib import Path
import pytest
from shared_core.core import ContractViolation
from v5_1.notifications import V51NotificationService

def ownership(path,authorized):
    path.write_text(json.dumps({"production_owner":"v5.1","notifications_owner":"v5.1","authorized":authorized}),encoding="utf-8")

def test_notification_refuses_without_explicit_ownership(tmp_path):
    manifest=tmp_path/"owner.json";ownership(manifest,False)
    service=V51NotificationService(tmp_path,manifest,token="test-only",transport=lambda req:(200,{"code":200,"msg":"请求成功"}))
    with pytest.raises(ContractViolation,match="ownership"):service.send(trade_date="2026-08-28",stage="morning_notification",entity_id="v51mp1-x",title="x",content="x",recorded_at="2026-08-28T09:35:10+08:00")

@pytest.mark.parametrize("status,body",[(500,{"code":200,"msg":"请求成功"}),(200,{"code":500,"msg":"请求成功"}),(200,{"code":200,"msg":"queued maybe"})])
def test_notification_requires_http_provider_and_explicit_accepted_semantics(tmp_path,status,body):
    manifest=tmp_path/"owner.json";ownership(manifest,True)
    service=V51NotificationService(tmp_path,manifest,token="test-only",transport=lambda req:(status,body))
    with pytest.raises(ContractViolation,match="ACCEPTED"):service.send(trade_date="2026-08-28",stage="morning_notification",entity_id="v51mp1-x",title="x",content="x",recorded_at="2026-08-28T09:35:10+08:00")

def test_notification_mock_success_is_content_addressed_and_idempotent(tmp_path):
    manifest=tmp_path/"owner.json";ownership(manifest,True);calls=[]
    service=V51NotificationService(tmp_path,manifest,token="test-only",transport=lambda req:(calls.append(req) or (200,{"code":200,"msg":"请求成功"})))
    kwargs={"trade_date":"2026-08-28","stage":"confirmation_notification","entity_id":"v51confirm1-x","title":"x","content":"body","recorded_at":"2026-08-28T14:50:30+08:00"}
    first=service.send(**kwargs);second=service.send(**kwargs);path=tmp_path/"notification_receipts"/"2026-08-28"/f"{first.receipt_id}.json"
    assert first.accepted and second.receipt_id==first.receipt_id and path.exists() and json.loads(path.read_text(encoding="utf-8"))["entity_id"]=="v51confirm1-x"
    assert "test-only" not in path.read_text(encoding="utf-8")
