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

def test_challenger_only_sell_snapshot_is_not_rejected_as_baseline_unfilled():
    with TemporaryDirectory() as d,patch("v5.task_runner.paper_sell",return_value={"outcome":"NO_BASELINE_POSITIONS_SHARED_SNAPSHOT","events":[],"snapshot_id":"shared-sell","execution_observed_at":"2026-08-17T09:30:10+08:00","sell_observation_id":"obs"}),patch("v5.task_runner.load_snapshot",return_value=object()),patch("v5.task_runner.challenger_paper_sell",return_value={"outcome":"FILLED"}),patch("v5.task_runner.finalize_due",return_value=[]) as finalize:
        result=run(Path(d),"paper_sell",now=datetime(2026,8,17,9,30,10,tzinfo=CHINA_TZ),clock_checker=lambda:{"passed":True,"reason":"OK"});assert result["passed"] is True and finalize.called

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

def test_baseline_empty_does_not_skip_challenger_when_shared_execution_exists():
    with TemporaryDirectory() as d,patch("v5.task_runner.paper_buy",return_value={"outcome":"NO_CANDIDATE","events":[],"execution_snapshot_id":"shared"}),patch("v5.task_runner.load_snapshot",return_value=object()),patch("v5.task_runner.challenger_paper_buy",return_value={"outcome":"FILLED"}) as challenger:
        root=Path(d);from v5.shadow_schedule import ShadowScheduler
        ShadowScheduler(root).record("confirmation","2026-08-14","SUCCESS",NOW,{})
        result=run(root,"paper_buy",now=NOW);assert result["passed"] is True and result["run"]["details"]["challenger"]["outcome"]=="SUCCESS" and challenger.called

def test_authorized_empty_confirmation_is_a_hashed_noop_without_ledger_write():
    with TemporaryDirectory() as d:
        root=Path(d);(root/"ownership.json").write_text(json.dumps({"schema_version":"v5-ownership-v1","paper_writer":"v5","scheduler":"v5","dashboard":"v5","notifications":"v5","authorized":True}),encoding="utf-8")
        confirmation=ConfirmationV5("2026-08-14",NOW.isoformat(),"v5mp1-test","funnel1-test","ms1-test","mstate1-test",(),(),"EMPTY").to_dict();path=root/"confirmations/2026-08-14/c.json";path.parent.mkdir(parents=True);path.write_text(json.dumps(confirmation),encoding="utf-8")
        pointer=root/"frozen/2026-08-14/signal.json";pointer.parent.mkdir(parents=True);pointer.write_text(json.dumps({"snapshot_id":"ms1-test","frozen_at":"2026-08-14T14:49:10+08:00"}),encoding="utf-8")
        pool=root/"morning_pools/2026-08-14/p.json";pool.parent.mkdir(parents=True);pool.write_text(json.dumps({"pool_id":"v5mp1-test","created_at":"2026-08-14T09:25:10+08:00"}),encoding="utf-8")
        market=root/"market_states/2026-08-14/m.json";market.parent.mkdir(parents=True);market.write_text(json.dumps({"market_state_id":"m","regime":"NEUTRAL","total_amount":1_000_000_000_000,"median_change":0}),encoding="utf-8")
        challenger=root/"challengers/volume_price_v1/confirmations/2026-08-14/v5chcd1-empty.json";challenger.parent.mkdir(parents=True);challenger.write_text(json.dumps({"confirmation_id":"v5chcd1-empty","decided_at":NOW.isoformat(),"outcome":"EMPTY","candidates":[]}),encoding="utf-8")
        result=paper_buy(root,now=NOW)
        assert result["outcome"]=="NO_CANDIDATE" and result["confirmation_id"]==confirmation["confirmation_id"] and result["opportunity_id"].startswith("opp1-")
        assert not (root/"paper/events.json").exists()

def test_unfilled_sell_attempt_never_persists_comparison_baseline():
    source=(Path(__file__).resolve().parents[1]/"v5/jobs.py").read_text(encoding="utf-8")
    outcomes=source.index('outcomes=[event.outcome for event in events]')
    complete_gate=source.index('if outcomes and all(value=="FILLED" for value in outcomes):',outcomes)
    baseline_write=source.index('production.save_baseline(',complete_gate)
    assert outcomes < complete_gate < baseline_write
