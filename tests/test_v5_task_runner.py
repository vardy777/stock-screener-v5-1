from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from v5.core import CHINA_TZ
from v5.task_runner import dependencies_for,inside_window,run

def at(hour,minute,second=0):
    return datetime(2026,8,14,hour,minute,second,tzinfo=CHINA_TZ)

def test_strict_market_tasks_have_fail_closed_time_windows():
    assert inside_window("morning_pool",at(9,25,5))
    assert not inside_window("morning_pool",at(9,30))
    assert inside_window("feature_freeze",at(14,49))
    assert not inside_window("feature_freeze",at(14,50))
    assert inside_window("confirmation",at(14,50))
    assert not inside_window("confirmation",at(14,53))

def test_late_start_records_failure_without_calling_market_producer():
    with TemporaryDirectory() as d,patch("v5.task_runner.produce") as producer:
        result=run(Path(d),"morning_pool",now=at(9,30))
        assert result["passed"] is False
        assert "outside allowed window" in result["run"]["details"]["error"]
        producer.assert_not_called()

def test_in_window_task_executes_and_records_success():
    with TemporaryDirectory() as d,patch("v5.task_runner.produce",return_value={"pool_id":"v5mp1-test"}) as producer:
        result=run(Path(d),"morning_pool",now=at(9,25,5),clock_checker=lambda:{"passed":True,"reason":"OK"})
        assert result["passed"] is True
        assert result["run"]["details"]["pool_id"]=="v5mp1-test"
        assert result["run"]["details"]["challenger"]["outcome"]=="FAILED"
        assert "context" in result["run"]["details"]["challenger"]["details"]["error"]
        producer.assert_called_once()

def test_missing_upstream_without_prior_alert_emits_one_dependency_alert():
    with TemporaryDirectory() as d,patch("v5.task_runner.send") as sender,patch("v5.task_runner.send_failure",return_value={"outcome":"ACCEPTED"}) as alert:
        root=Path(d);result=run(root,"morning_push",now=at(9,25,20),failure_alert_env=root/".env")
        assert result["passed"] is False and "dependencies incomplete: morning_pool" in result["run"]["details"]["error"]
        assert result["run"]["details"]["failure_alert"]["outcome"]=="ACCEPTED"
        alert.assert_called_once()
        sender.assert_not_called()

def test_downstream_suppresses_duplicate_only_after_upstream_alert_was_accepted():
    with TemporaryDirectory() as d,patch("v5.task_runner.produce",side_effect=RuntimeError("source down")),patch("v5.task_runner.send_failure",return_value={"outcome":"ACCEPTED"}) as alert:
        root=Path(d);failed=run(root,"morning_pool",now=at(9,25,5),failure_alert_env=root/".env",clock_checker=lambda:{"passed":True,"reason":"OK"})
        assert failed["run"]["details"]["failure_alert"]["outcome"]=="ACCEPTED"
        result=run(root,"morning_push",now=at(9,25,20),failure_alert_env=root/".env")
        assert result["run"]["details"]["failure_alert_suppressed"]=="UPSTREAM_ROOT_CAUSE_ALREADY_ALERTED"
        assert alert.call_count==1

def test_failed_upstream_never_satisfies_dependency():
    with TemporaryDirectory() as d,patch("v5.task_runner.send") as sender:
        root=Path(d)
        run(root,"morning_pool",now=at(9,25,5),clock_checker=lambda:{"passed":True,"reason":"OK"})
        # The producer is not patched in this branch and therefore fails; a
        # failed upstream record must still not satisfy the dependency.
        result=run(root,"morning_push",now=at(9,25,21));assert result["passed"] is False
        sender.assert_not_called()

def test_tampered_successful_upstream_cannot_unlock_notification():
    with TemporaryDirectory() as d,patch("v5.task_runner.produce",return_value={"pool_id":"v5mp1-test"}),patch("v5.task_runner.send") as sender:
        root=Path(d);run(root,"morning_pool",now=at(9,25,5),clock_checker=lambda:{"passed":True,"reason":"OK"})
        path=next((root/"runs/2026-08-14").glob("*.json"));row=json.loads(path.read_text(encoding="utf-8"));row["details"]["pool_id"]="tampered";path.write_text(json.dumps(row),encoding="utf-8")
        result=run(root,"morning_push",now=at(9,25,20))
        assert result["passed"] is False and "dependencies incomplete: morning_pool" in result["run"]["details"]["error"]
        sender.assert_not_called()

def test_market_capture_fails_before_provider_call_when_clock_is_unhealthy():
    with TemporaryDirectory() as d,patch("v5.task_runner.produce") as producer:
        result=run(Path(d),"morning_pool",now=at(9,25,5),clock_checker=lambda:{"passed":False,"reason":"WINDOWS_TIME_OFFSET_TOO_LARGE"})
        assert result["passed"] is False and "causal clock rejected" in result["run"]["details"]["error"]
        producer.assert_not_called()

def test_diagnostic_and_maintenance_tasks_are_never_blocked_by_business_outcomes():
    with TemporaryDirectory() as d:
        root=Path(d)
        assert dependencies_for(root,"health_check")==()
        assert dependencies_for(root,"maintenance")==()
        (root/"ownership.json").write_text(
            '{"schema_version":"v5-ownership-v1","paper_writer":"v5","scheduler":"v5","dashboard":"v5","notifications":"v5","authorized":true}',
            encoding="utf-8",
        )
        assert dependencies_for(root,"health_check")==()

def test_failed_health_report_is_preserved_and_alerted():
    with TemporaryDirectory() as d,patch("v5.task_runner.health",return_value={"passed":False,"checks":{"morning_fact_exists":False}}),patch("v5.task_runner.send_failure",return_value={"outcome":"ACCEPTED"}) as alert:
        root=Path(d);result=run(root,"health_check",now=at(14,53),failure_alert_env=root/".env")
        assert result["passed"] is False
        assert result["run"]["details"]["checks"]["morning_fact_exists"] is False
        assert result["run"]["details"]["failure_alert"]["outcome"]=="ACCEPTED"
        alert.assert_called_once()

def test_health_suppresses_only_derived_failures_after_upstream_alert():
    checks={"morning_fact_exists":False,"morning_notification_accepted":False,
            "confirmation_fact_exists":False,"confirmation_notification_accepted":False,
            "lineage_accepted":False,"paper_ledger_reconciled":True}
    with TemporaryDirectory() as d,patch("v5.task_runner.produce",side_effect=RuntimeError("source down")), \
         patch("v5.task_runner.health",return_value={"passed":False,"checks":checks}), \
         patch("v5.task_runner.send_failure",return_value={"outcome":"ACCEPTED"}) as alert:
        root=Path(d)
        run(root,"morning_pool",now=at(9,25,5),failure_alert_env=root/".env",clock_checker=lambda:{"passed":True})
        result=run(root,"health_check",now=at(14,53),failure_alert_env=root/".env")
        assert result["run"]["details"]["failure_alert_suppressed"]=="UPSTREAM_ROOT_CAUSE_ALREADY_ALERTED"
        assert alert.call_count==1
