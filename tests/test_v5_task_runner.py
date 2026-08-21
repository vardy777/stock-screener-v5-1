from datetime import datetime
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

def test_market_capture_fails_before_provider_call_when_clock_is_unhealthy():
    with TemporaryDirectory() as d,patch("v5.task_runner.produce") as producer:
        result=run(Path(d),"morning_pool",now=at(9,25,5),clock_checker=lambda:{"passed":False,"reason":"WINDOWS_TIME_OFFSET_TOO_LARGE"})
        assert result["passed"] is False and "causal clock rejected" in result["run"]["details"]["error"]
        producer.assert_not_called()

def test_health_dependencies_include_paper_tasks_only_after_authorized_cutover():
    with TemporaryDirectory() as d:
        root=Path(d)
        assert "paper_buy" not in dependencies_for(root,"health_check")
        (root/"ownership.json").write_text(
            '{"schema_version":"v5-ownership-v1","paper_writer":"v5","scheduler":"v5","dashboard":"v5","notifications":"v5","authorized":true}',
            encoding="utf-8",
        )
        dependencies=dependencies_for(root,"health_check")
        assert dependencies[-2:]==("paper_sell","paper_buy")
