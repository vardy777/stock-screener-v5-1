from datetime import datetime
from v5.core import CHINA_TZ,ContractViolation
from v5.recovery_observation import run

def test_recovery_observation_rejects_outside_narrow_afternoon_window(tmp_path):
    try:run(tmp_path,now=datetime(2026,8,21,11,50,tzinfo=CHINA_TZ),transport=lambda:{"code":200})
    except ContractViolation as exc:assert "outside" in str(exc)
    else:raise AssertionError("must fail closed")

def test_recovery_source_declares_no_strategy_or_paper_eligibility():
    text=open("v5/recovery_observation.py",encoding="utf-8").read()
    assert '"strict_0925_sample":False' in text
    assert '"eligible_for_confirmation":False' in text
    assert '"eligible_for_paper":False' in text
