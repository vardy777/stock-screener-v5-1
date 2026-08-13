from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from datetime import datetime
import pytest
from v5.alerts import send_failure
from v5.core import CHINA_TZ
from v5.task_runner import run

def test_operational_alert_requires_real_200_and_is_idempotent():
    with TemporaryDirectory() as d:
        root=Path(d);env=root/".env";env.write_text("PUSHPLUS_TOKEN=secret",encoding="utf-8");calls=[]
        with pytest.raises(RuntimeError):send_failure(root,"2026-08-14","morning_pool","no universe",env,transport=lambda:{"code":500})
        assert not list((root/"alerts").rglob("*.json")) and list((root/"alert_attempts").rglob("*.json"))
        accepted=send_failure(root,"2026-08-14","morning_pool","no universe",env,transport=lambda:(calls.append(1) or {"code":200}));assert accepted["outcome"]=="ACCEPTED"
        assert send_failure(root,"2026-08-14","morning_pool","no universe",env,transport=lambda:calls.append(2))["outcome"]=="ACCEPTED" and calls==[1]

def test_task_failure_remains_failed_even_when_alert_is_accepted():
    now=datetime(2026,8,14,9,24,30,tzinfo=CHINA_TZ)
    with TemporaryDirectory() as d,patch("v5.task_runner.produce",side_effect=RuntimeError("source down")),patch("v5.task_runner.send_failure",return_value={"outcome":"ACCEPTED"}):
        result=run(Path(d),"morning_pool",now=now,failure_alert_env=Path(d)/".env",clock_checker=lambda:{"passed":True,"reason":"OK"})
        assert result["passed"] is False and result["run"]["details"]["failure_alert"]["outcome"]=="ACCEPTED"
