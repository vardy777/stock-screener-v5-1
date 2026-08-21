import json
from datetime import datetime,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from v5.core import CHINA_TZ
from v5.jobs import paper_buy,paper_sell
from v5.task_runner import run
from v5.decision_flow import ConfirmationV5

NOW=datetime(2026,8,14,14,50,40,tzinfo=CHINA_TZ)

def test_paper_entrypoints_are_implemented_but_fail_closed_without_v5_ownership():
    with TemporaryDirectory() as d:
        root=Path(d)
        result=run(root,"paper_buy",now=NOW)
        assert result["passed"] is False and "dependencies incomplete" in result["run"]["details"]["error"]
        # Even direct invocation cannot bypass the single-writer ownership gate.
        try:paper_buy(root,now=NOW)
        except Exception as exc:assert "does not own paper_writer" in str(exc)
        else:raise AssertionError("V5 paper writer must remain locked")
        sell=run(root,"paper_sell",now=datetime(2026,8,17,9,30,10,tzinfo=CHINA_TZ),clock_checker=lambda:{"passed":True,"reason":"OK"})
        assert sell["passed"] is False and "does not own paper_writer" in sell["run"]["details"]["error"]

def test_v5_task_cli_exposes_all_nine_business_tasks():
    text=(Path(__file__).resolve().parents[1]/"v5/scripts/v5_task.py").read_text(encoding="utf-8")
    for task in ("morning_pool","morning_push","paper_sell","feature_freeze","confirmation","confirmation_push","paper_buy","health_check","maintenance"):assert f'"{task}"' in text

def test_authorized_sell_with_no_positions_or_baseline_is_explicit_noop():
    with TemporaryDirectory() as d:
        root=Path(d);(root/"ownership.json").write_text(json.dumps({"schema_version":"v5-ownership-v1","paper_writer":"v5","scheduler":"v5","dashboard":"v5","notifications":"v5","authorized":True}),encoding="utf-8")
        result=paper_sell(root,now=datetime(2026,8,17,9,30,10,tzinfo=CHINA_TZ));assert result["outcome"]=="NO_POSITIONS_OR_BASELINE" and result["events"]==[] and result["baselines"]==[]

def test_task_runner_marks_unfilled_paper_sell_failed_after_preserving_result():
    with TemporaryDirectory() as d,patch("v5.task_runner.paper_sell",return_value={"outcome":"UNFILLED","events":[{"reason":"INSUFFICIENT_BID_DEPTH"}]}) as seller:
        root=Path(d);result=run(root,"paper_sell",now=datetime(2026,8,17,9,30,10,tzinfo=CHINA_TZ),clock_checker=lambda:{"passed":True,"reason":"OK"})
        assert result["passed"] is False and "paper sell incomplete: UNFILLED" in result["run"]["details"]["error"] and seller.called

def test_task_runner_marks_rejected_paper_buy_failed():
    with TemporaryDirectory() as d,patch("v5.task_runner.paper_buy",return_value={"outcome":"REJECTED","reason":"INSUFFICIENT_CASH"}) as buyer:
        root=Path(d);from v5.shadow_schedule import ShadowScheduler
        ShadowScheduler(root).record("confirmation","2026-08-14","SUCCESS",NOW,{})
        result=run(root,"paper_buy",now=NOW)
        assert result["passed"] is False and "paper buy rejected: INSUFFICIENT_CASH" in result["run"]["details"]["error"] and buyer.called

def test_task_runner_accepts_explicit_no_candidate_as_valid_empty_position_day():
    with TemporaryDirectory() as d,patch("v5.task_runner.paper_buy",return_value={"outcome":"NO_CANDIDATE","events":[]}) as buyer:
        root=Path(d);from v5.shadow_schedule import ShadowScheduler
        ShadowScheduler(root).record("confirmation","2026-08-14","SUCCESS",NOW,{})
        result=run(root,"paper_buy",now=NOW)
        assert result["passed"] is True and result["run"]["details"]["outcome"]=="NO_CANDIDATE" and buyer.called

def test_authorized_empty_confirmation_is_a_hashed_noop_without_ledger_write():
    with TemporaryDirectory() as d:
        root=Path(d);(root/"ownership.json").write_text(json.dumps({"schema_version":"v5-ownership-v1","paper_writer":"v5","scheduler":"v5","dashboard":"v5","notifications":"v5","authorized":True}),encoding="utf-8")
        confirmation=ConfirmationV5("2026-08-14",NOW.isoformat(),"v5mp1-test","funnel1-test","ms1-test","mstate1-test",(),(),"EMPTY").to_dict();path=root/"confirmations/2026-08-14/c.json";path.parent.mkdir(parents=True);path.write_text(json.dumps(confirmation),encoding="utf-8")
        pointer=root/"frozen/2026-08-14/signal.json";pointer.parent.mkdir(parents=True);pointer.write_text(json.dumps({"snapshot_id":"ms1-test"}),encoding="utf-8")
        result=paper_buy(root,now=NOW)
        assert result["outcome"]=="NO_CANDIDATE" and result["confirmation_id"]==confirmation["confirmation_id"]
        assert not (root/"paper/events.json").exists()

def test_unfilled_sell_attempt_never_persists_comparison_baseline():
    source=(Path(__file__).resolve().parents[1]/"v5/jobs.py").read_text(encoding="utf-8")
    outcomes=source.index('outcomes=[event.outcome for event in events]')
    complete_gate=source.index('if outcomes and all(value=="FILLED" for value in outcomes):',outcomes)
    baseline_write=source.index('production.save_baseline(',complete_gate)
    assert outcomes < complete_gate < baseline_write
