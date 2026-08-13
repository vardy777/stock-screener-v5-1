from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from v5.core import CHINA_TZ
from v5.task_runner import inside_window,run

def at(hour,minute,second=0):
    return datetime(2026,8,14,hour,minute,second,tzinfo=CHINA_TZ)

def test_strict_market_tasks_have_fail_closed_time_windows():
    assert inside_window("morning_pool",at(9,24,30))
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
        result=run(Path(d),"morning_pool",now=at(9,24,30))
        assert result["passed"] is True
        assert result["run"]["details"]["pool_id"]=="v5mp1-test"
        producer.assert_called_once()
