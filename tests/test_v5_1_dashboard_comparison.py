import json
from datetime import datetime
import pytest
from shared_core.core import ContractViolation
from v5_1.comparison import compare
from v5_1.dashboard import render
from v5_1.read_model import build,load_projection,production_state,save_projection
from v5_1 import BASELINE_STRATEGY_VERSION,CLOSESCAN_STRATEGY_VERSION
from v5_1.storage import V51FactStore
from v5_1.decision import BaselineConfirmationV51
from v5_1.execution import ExecutionObservationV51
from v5_1.production_read_model import AcceptanceFactV51,ExecutionResultFactV51,ImmutableReadModelBuilder,ProductionFailureFactV51,ProductionRunFactV51

def row(day,value,code="600000",traded=True,strategy_version=BASELINE_STRATEGY_VERSION):return {"trade_date":day,"net_return":value,"net_pnl":value*30000,"slippage":.001,"turnover":60000,"selected_code":code,"traded":traded,"cohort":"STRICT","system_version":"5.1","strategy_version":strategy_version}
def model(day="2026-08-28",failed=None):
 comparison=compare([row(day,.01)],[row(day,.02,"600001",strategy_version=CLOSESCAN_STRATEGY_VERSION)])
 return build(trade_date=day,master={"status":"VERIFIED","count":5217,"version":"smv1-x","last_verified_at":"2026-08-27 18:00","freshness":"PREVIOUS_COMPLETED_CYCLE","sse_status":"PENDING_LIVE_ACCEPTANCE","szse_status":"PENDING_LIVE_ACCEPTANCE","independent_sources":"fixtures accepted; live pending"},tradability={"status":"ACCEPTED","coverage":"100%"},market={"sina_coverage":"96%","tencent_coverage":"97%","consensus":"96%"},baseline={"complete":True,"confirmation_outcome":"EMPTY","candidates":[],"decision_snapshot_id":"ms1-decision","execution_snapshot_id":"ms1-execution"},closescan={"complete":True,"selection_outcome":"EMPTY","candidates":[]},comparison=comparison,accounts={"baseline":{"cash":100000},"closescan":{"cash":100000}},health={"production_complete":failed is None,"failed_component":failed,"confirmation_outcome":"EMPTY"})

def test_comparison_is_strict_paired_and_tracks_drawdown_agreement_states():
 result=compare([row("2026-08-28",.1),row("2026-08-31",-.2,"600001")],[row("2026-08-28",.05,strategy_version=CLOSESCAN_STRATEGY_VERSION),row("2026-09-01",.03,"600002",strategy_version=CLOSESCAN_STRATEGY_VERSION)])
 assert result["paired_sessions"]==1 and result["selection_agreement_rate"]==1 and result["baseline"]["max_drawdown"]<0 and result["session_states"]=={"both_traded":1,"baseline_only":1,"closescan_only":1,"both_flat":0}
 proxy=compare([row("2026-08-28",.1),{**row("2026-08-28",.9),"cohort":"PROXY"},{**row("2026-08-28",.8),"cohort":"PROXY"}],[]);assert proxy["baseline"]["strict_round_trips"]==1

def test_comparison_is_versioned_content_addressed_fact(tmp_path):
 result=compare([row("2026-08-28",.01)],[row("2026-08-28",.02,strategy_version=CLOSESCAN_STRATEGY_VERSION)])
 path=V51FactStore(tmp_path).save("comparisons",result)
 assert path.name==result["comparison_id"]+".json" and result["system_version"]=="5.1"

def test_dashboard_has_distinct_pages_v51_timeline_and_no_g1():
 m=model();pages={view:render(m,view) for view in ("today","candidates","validation","account","health")}
 assert len(set(pages.values()))==5
 for page in pages.values():
  assert "V5.1" in page and "G1" not in page and "09:25" not in page
 assert "09:35 Morning Pool" in pages["today"] and "Security Master" in pages["today"]
 assert "CLOSESCAN · FULL-MARKET @ 14:49" in pages["candidates"]
 assert "STRICT ONLY" in pages["validation"] and "Strict Equity Curve" in pages["validation"]
 assert "Baseline Account" in pages["account"] and "CloseScan Account" in pages["account"] and "Decision Snapshot" in pages["account"] and "Execution Snapshot" in pages["account"]

def test_fail_closed_is_not_flat_and_incident_history_is_preserved():
 assert production_state(complete=True,confirmation_outcome="EMPTY")=="ACTIVE_FLAT"
 assert production_state(complete=True,confirmation_outcome="NO_CANDIDATE")=="ACTIVE_FLAT"
 assert production_state(failed_component="DATA_FAILED")=="FAIL_CLOSED"
 assert production_state(complete=True,traded=True,confirmation_outcome="BUY_CANDIDATE")=="TRADED"
 assert production_state()=="WAITING"
 failed=model("2026-08-28","SINA_CONSENSUS");assert failed.state=="FAIL_CLOSED" and failed.baseline["state"]=="FAIL_CLOSED" and "Failed component" in render(failed,"health")
 assert build(trade_date="2026-08-26",health={"failed_component":"UNIVERSE_FAILED"}).state=="FAIL_CLOSED"
 assert build(trade_date="2026-08-27",health={"failed_component":"MASTER_FAILED"}).state=="FAIL_CLOSED"
 assert build(trade_date="2026-08-24",baseline={"complete":True,"confirmation_outcome":"EMPTY"},health={"production_complete":True,"confirmation_outcome":"EMPTY"}).state=="ACTIVE_FLAT"
 assert build(trade_date="2026-08-25",baseline={"complete":True,"confirmation_outcome":"NO_CANDIDATE"},health={"production_complete":True,"confirmation_outcome":"NO_CANDIDATE"}).state=="ACTIVE_FLAT"

def test_dashboard_accounts_and_strategies_remain_independent():
 m=model();assert m.accounts["baseline"] is not m.accounts["closescan"] and m.baseline is not m.closescan
 assert m.comparison["cohort"]=="STRICT" and m.comparison["conclusion"]=="EVIDENCE_INSUFFICIENT"

def test_dashboard_projection_is_content_addressed_and_fail_closed(tmp_path):
 m=build(trade_date="2026-08-27",master={"count":5217},health={"production_complete":True});path=save_projection(tmp_path,m)
 assert load_projection(tmp_path,"2026-08-27").master["count"]==5217
 row=json.loads(path.read_text(encoding="utf-8"));row["master"]["count"]=1;path.write_text(json.dumps(row),encoding="utf-8")
 loaded=load_projection(tmp_path,"2026-08-27");assert loaded.state=="FAIL_CLOSED" and loaded.health["failed_component"]=="V5_1_READ_MODEL_INVALID"

def test_missing_dashboard_projection_never_falls_back_to_legacy(tmp_path):
 loaded=load_projection(tmp_path,"2026-08-27")
 assert loaded.state=="FAIL_CLOSED" and loaded.health["failed_component"]=="V5_1_READ_MODEL_MISSING"

def test_comparison_rejects_wrong_strategy_and_duplicate_strict_session():
 with pytest.raises(ContractViolation,match="identity"):compare([row("2026-08-28",.01,strategy_version=CLOSESCAN_STRATEGY_VERSION)],[])
 with pytest.raises(ContractViolation,match="duplicate STRICT"):compare([row("2026-08-28",.01),row("2026-08-28",.02)],[])

def test_immutable_read_model_builder_derives_active_flat_failure_and_trade(tmp_path):
 day="2026-08-28";store=V51FactStore(tmp_path)
 confirmation=BaselineConfirmationV51(day,"2026-08-28T14:50:00+08:00","v51mp1-x","ms1-decision","mstate1-x","funnel1-x",(),(),"EMPTY");store.save("confirmations",confirmation);acceptance=AcceptanceFactV51(day,"2026-08-28T15:20:00+08:00",(),(confirmation.confirmation_id,),"PASS","ACTIVE_FLAT","PENDING","PENDING","PENDING_REAL_WINDOW");store.save("acceptance_facts",acceptance);store.save("production_runs",ProductionRunFactV51(day,"acceptance","2026-08-28T15:20:01+08:00","SUCCESS",acceptance.acceptance_id))
 builder=ImmutableReadModelBuilder(tmp_path);flat=builder.build(day);assert flat.state=="ACTIVE_FLAT" and flat.health["lineage"]=="VERIFIED"
 failed_root=tmp_path/"failed";failed_store=V51FactStore(failed_root);failed_store.save("production_failures",ProductionFailureFactV51(day,"SECURITY_MASTER","2026-08-28T08:30:00+08:00","STALE"));assert ImmutableReadModelBuilder(failed_root).build(day).state=="FAIL_CLOSED"
 traded_root=tmp_path/"traded";traded_store=V51FactStore(traded_root);confirmation2=BaselineConfirmationV51(day,"2026-08-28T14:50:00+08:00","v51mp1-y","ms1-decision-y","mstate1-y","funnel1-y",({"code":"600000"},),(),"BUY_CANDIDATE");traded_store.save("confirmations",confirmation2);observation=ExecutionObservationV51(day,"BUY",BASELINE_STRATEGY_VERSION,"decision-y","ms1-decision-y","2026-08-28T14:50:00+08:00","ms1-execution-y","2026-08-28T14:50:42+08:00","2026-08-28T14:50:43+08:00","600000",10.0,1000,10.01,1000);traded_store.save("execution_observations",observation);traded_store.save("execution_results",ExecutionResultFactV51(day,BASELINE_STRATEGY_VERSION,"BUY",observation.observation_id,"event-y","FILLED","2026-08-28T14:50:43+08:00"));acceptance2=AcceptanceFactV51(day,"2026-08-28T15:20:00+08:00",(),(confirmation2.confirmation_id,),"PASS","PASS","PENDING","PENDING","PENDING_REAL_WINDOW");traded_store.save("acceptance_facts",acceptance2);traded_store.save("production_runs",ProductionRunFactV51(day,"acceptance","2026-08-28T15:20:01+08:00","SUCCESS",acceptance2.acceptance_id));assert ImmutableReadModelBuilder(traded_root).build(day).state=="TRADED"

def test_immutable_read_model_builder_quarantines_missing_execution_lineage(tmp_path):
 day="2026-08-28";store=V51FactStore(tmp_path);store.save("execution_results",ExecutionResultFactV51(day,BASELINE_STRATEGY_VERSION,"BUY","v51execobs1-missing","event-x","FILLED","2026-08-28T14:50:43+08:00"));model=ImmutableReadModelBuilder(tmp_path).build(day);assert model.state=="FAIL_CLOSED" and model.health["lineage"]=="QUARANTINED"

def test_dashboard_empty_historical_and_non_trading_days_do_not_infer_missed(tmp_path):
 builder=ImmutableReadModelBuilder(tmp_path)
 historical=builder.build("2026-08-27",as_of=datetime.fromisoformat("2026-08-28T10:00:00+08:00"));assert historical.state=="WAITING" and historical.health["lineage"]=="NO_EVIDENCE"
 weekend=builder.build("2026-08-29",as_of=datetime.fromisoformat("2026-08-29T10:00:00+08:00"));assert weekend.state=="WAITING" and weekend.health["lineage"]=="NO_EVIDENCE"

def test_dashboard_latest_success_supersedes_old_failure_but_partial_is_not_verified(tmp_path):
 day="2026-08-28";store=V51FactStore(tmp_path);store.save("production_failures",ProductionFailureFactV51(day,"morning_pool","2026-08-28T09:35:01+08:00","TRANSIENT"));confirmation=BaselineConfirmationV51(day,"2026-08-28T14:50:00+08:00","v51mp1-x","ms1-x","mstate1-x","funnel1-x",(),(),"EMPTY");store.save("confirmations",confirmation);store.save("production_runs",ProductionRunFactV51(day,"morning_pool","2026-08-28T09:35:30+08:00","SUCCESS",confirmation.confirmation_id));model=ImmutableReadModelBuilder(tmp_path).build(day);assert model.health["failed_component"] is None and model.health["lineage"]=="PARTIAL" and model.state=="WAITING"

def test_dashboard_forged_acceptance_reference_is_quarantined(tmp_path):
 day="2026-08-28";store=V51FactStore(tmp_path);acceptance=AcceptanceFactV51(day,"2026-08-28T15:20:00+08:00",(),(),"PASS","ACTIVE_FLAT","PENDING","PENDING","PENDING_REAL_WINDOW");store.save("acceptance_facts",acceptance);store.save("production_runs",ProductionRunFactV51(day,"acceptance","2026-08-28T15:20:01+08:00","SUCCESS","v51accept1-forged"));model=ImmutableReadModelBuilder(tmp_path).build(day);assert model.state=="WAITING" and model.health["lineage"]=="PARTIAL"
