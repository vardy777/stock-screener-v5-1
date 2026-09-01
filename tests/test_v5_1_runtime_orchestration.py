from datetime import datetime,timedelta
from pathlib import Path
import json
import pytest
from shared_core.core import CHINA_TZ,ContractViolation
from v5_1.runtime import V51Runtime
from v5_1.production_read_model import ImmutableReadModelBuilder
from shared_core.market_snapshot import MarketSnapshotV1,QuoteV1
from types import SimpleNamespace
import subprocess,sys
from shared_core.calendar import TradingCalendar
from v5_1.production_read_model import StageOutcomeFactV51,AcceptanceFactV51,ProductionFailureFactV51,ExecutionResultFactV51

class OpenCalendar:
    def is_open(self,day):return True
    def next_open(self,day):return day
class NoopProvider:pass
class NoopMaster:pass

def runtime(tmp_path,at,mode="SHADOW"):
    return V51Runtime(tmp_path,mode=mode,clock=lambda:datetime.fromisoformat(at),provider=NoopProvider(),master_provider=NoopMaster(),calendar=OpenCalendar())

def test_actual_clock_rejects_missed_window_and_writes_failure(tmp_path):
    result=runtime(tmp_path,"2026-08-27T14:00:00+08:00").run("morning_pool")
    assert result["passed"] is False
    assert "outside actual window" in result["error"]
    assert list((tmp_path/"production_failures"/"2026-08-27").glob("*.json"))

def test_replay_storage_cannot_be_named_strict(tmp_path):
    with pytest.raises(ContractViolation,match="cannot target production or shadow"):
        V51Runtime(Path(__file__).parents[1]/"v5_1"/"data",mode="REPLAY",provider=NoopProvider(),master_provider=NoopMaster(),calendar=OpenCalendar())

def test_single_writer_lock_rejects_duplicate_process(tmp_path):
    rt=runtime(tmp_path,"2026-08-27T09:35:10+08:00")
    with rt._lock("2026-08-27","morning_pool"):
        with pytest.raises(ContractViolation,match="single-writer"):
            with rt._lock("2026-08-27","morning_pool"):pass

def test_stale_crash_lock_is_recovered(tmp_path):
    rt=runtime(tmp_path,"2026-08-27T09:35:10+08:00");path=tmp_path/"locks"/"2026-08-27-morning_pool.lock";path.parent.mkdir(parents=True);path.write_text("99999999",encoding="ascii")
    with rt._lock("2026-08-27","morning_pool"):assert path.exists()
    # Metadata persists for audit; ownership is the held OS file lock, not file existence.
    assert path.exists()

def test_windows_stage_lock_allows_only_one_process(tmp_path):
    code="""
from datetime import datetime
from v5_1.runtime import V51Runtime
class C:
 def is_open(self,d): return True
class N: pass
r=V51Runtime(r'%s',mode='SHADOW',clock=lambda:datetime.fromisoformat('2026-08-27T09:35:10+08:00'),provider=N(),master_provider=N(),calendar=C())
with r._lock('2026-08-27','morning_pool'):
 print('READY',flush=True)
 input()
""" % str(tmp_path).replace("\\","\\\\")
    child=subprocess.Popen([sys.executable,"-c",code],cwd=Path(__file__).parents[1],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip()=="READY"
        rt=runtime(tmp_path,"2026-08-27T09:35:10+08:00")
        with pytest.raises(ContractViolation,match="single-writer"):
            with rt._lock("2026-08-27","morning_pool"):pass
    finally:
        child.stdin.write("\n");child.stdin.flush();child.wait(timeout=10)

def test_empty_fact_dashboard_changes_after_missed_0935(tmp_path):
    builder=ImmutableReadModelBuilder(tmp_path)
    before=builder.build("2026-08-27",as_of=datetime(2026,8,27,9,0,tzinfo=CHINA_TZ))
    assert before.state=="WAITING" and before.health["lineage"]=="NO_EVIDENCE"
    after=builder.build("2026-08-27",as_of=datetime(2026,8,27,10,0,tzinfo=CHINA_TZ))
    assert after.state=="FAIL_CLOSED" and after.health["failed_component"]=="MISSED_0935_MORNING_WINDOW"

def test_replay_bypasses_wallclock_only_in_non_strict_root(tmp_path):
    rt=runtime(tmp_path/"replay","2026-08-27T14:00:00+08:00",mode="REPLAY")
    rt._window("morning_pool",rt.now())

class ReplayMaster:
    provider_family="eastmoney";source_id="eastmoney_replay_directory"
    def discover(self):return ("600000","000001"),{"strict_evidence":False}
class ReplayProvider:
    def __init__(self,clock):self.clock=clock
    def acquire(self,codes,*,trade_date,stage,now):
        observed=now+timedelta(seconds=1) if stage=="sell_execution" else now;quotes=[]
        for i,code in enumerate(codes):
            price=10.3+i*.1
            quotes.append(QuoteV1.from_mapping({"code":code,"name":"浦发银行" if code=="600000" else "平安银行","trade_date":trade_date,"exchange_time":observed,"provider_time":observed,"received_at":observed,"last_price":price,"previous_close":10,"open_price":10.1,"high_price":10.5,"low_price":9.9,"bid1":price-.01,"bid1_volume":100000,"ask1":price+.01,"ask1_volume":100000,"volume":1000000,"amount":20000000+i*1000000,"halted":False,"limit_up":False,"limit_down":False,"provider":"v5_dual_source_conservative_consensus"}))
        source_a=MarketSnapshotV1.build(trade_date=trade_date,session=stage,batch_started_at=now,batch_completed_at=observed,quotes=[QuoteV1.from_mapping({**q.to_dict(),"provider":"sina_replay"}) for q in quotes],expected_codes=len(codes))
        source_b=MarketSnapshotV1.build(trade_date=trade_date,session=stage,batch_started_at=now,batch_completed_at=observed,quotes=[QuoteV1.from_mapping({**q.to_dict(),"provider":"tencent_replay"}) for q in quotes],expected_codes=len(codes))
        snapshot=MarketSnapshotV1.build(trade_date=trade_date,session=stage,batch_started_at=now,batch_completed_at=observed,quotes=quotes,expected_codes=len(codes))
        return SimpleNamespace(accepted=True,primary=snapshot,sources=(source_a,source_b),report={"consistent_ratio":1.0})

def test_full_day_replay_orchestrates_to_two_isolated_ledgers(tmp_path):
    current=[datetime.fromisoformat("2026-08-27T08:30:00+08:00")]
    rt=V51Runtime(tmp_path/"replay",mode="REPLAY",clock=lambda:current[0],provider=ReplayProvider(lambda:current[0]),master_provider=ReplayMaster(),calendar=TradingCalendar())
    for stage,at in [("preflight","2026-08-27T08:30:00+08:00"),("morning_observation","2026-08-27T09:32:00+08:00"),("morning_pool","2026-08-27T09:35:10+08:00"),("feature_freeze","2026-08-27T14:49:10+08:00"),("confirmation","2026-08-27T14:50:10+08:00"),("execution","2026-08-27T14:50:40+08:00")]:
        current[0]=datetime.fromisoformat(at);result=rt.run(stage);assert result["passed"],result
    assert (tmp_path/"replay"/"v5.1-baseline-0935-v1"/"paper"/"events.json").exists()
    assert (tmp_path/"replay"/"v5.1-closescan-v1"/"paper"/"events.json").exists()
    current[0]=datetime.fromisoformat("2026-08-27T14:53:00+08:00");assert rt.run("health")["passed"]
    current[0]=datetime.fromisoformat("2026-08-27T15:20:00+08:00");accepted=rt.run("acceptance");assert accepted["passed"] and accepted["details"]["projection_state"]=="TRADED"
    assert accepted["details"]["real_window_acceptance"]=="PRELIMINARY_ONLY" and accepted["details"]["round_trip_acceptance"]=="PENDING"
    duplicate=rt.run("acceptance");assert duplicate["passed"] and duplicate["accepted"] and duplicate["idempotent"] and duplicate["entity"]==accepted["run"]["entity_id"]
    current[0]=datetime.fromisoformat("2026-08-28T09:30:10+08:00");sold=rt.run("next_open_exit");assert sold["passed"],sold
    current[0]=datetime.fromisoformat("2026-08-28T09:31:10+08:00");round_accepted=rt.run("round_trip_acceptance");assert round_accepted["passed"],round_accepted
    assert round_accepted["details"]["strict_day_accepted"] is True and round_accepted["details"]["trade_count"]==2 and round_accepted["details"]["day_mode"]=="TRADED"
    for strategy in ("v5.1-baseline-0935-v1","v5.1-closescan-v1"):
        from shared_core.paper import PaperLedger
        ledger=PaperLedger(tmp_path/"replay"/strategy/"paper");assert ledger.reconcile()["passed"];assert ledger.state()["positions"]==[];assert len(ledger.round_trips())==1

def test_active_flat_requires_successful_pipeline_and_next_open_observation(tmp_path):
    current=[datetime.fromisoformat("2026-08-28T09:31:10+08:00")];rt=V51Runtime(tmp_path/"replay",mode="REPLAY",clock=lambda:current[0],provider=NoopProvider(),master_provider=NoopMaster(),calendar=TradingCalendar())
    preliminary=AcceptanceFactV51("2026-08-27","2026-08-27T15:20:00+08:00",(),(),"PASS","ACTIVE_FLAT","PENDING","PENDING","PRELIMINARY_ONLY");rt.store.save("acceptance_facts",preliminary);rt._record("2026-08-27","acceptance",datetime.fromisoformat("2026-08-27T15:20:00+08:00"),"SUCCESS",preliminary.acceptance_id)
    stage=StageOutcomeFactV51("2026-08-27","execution","ACTIVE_FLAT",("v5.1-baseline-0935-v1","v5.1-closescan-v1"),"2026-08-27T14:50:40+08:00","REPLAY","V51_REPLAY",False);rt.store.save("stage_outcomes",stage)
    exit_stage=StageOutcomeFactV51("2026-08-28","next_open_exit","NO_POSITIONS",("v5.1-baseline-0935-v1","v5.1-closescan-v1"),"2026-08-28T09:30:10+08:00","REPLAY","V51_REPLAY",False);rt.store.save("stage_outcomes",exit_stage);rt._record("2026-08-28","next_open_exit",datetime.fromisoformat("2026-08-28T09:30:10+08:00"),"SUCCESS",exit_stage.stage_outcome_id)
    result=rt.run("round_trip_acceptance");assert result["passed"],result
    assert result["details"]["day_mode"]=="ACTIVE_FLAT" and result["details"]["trade_count"]==0 and result["details"]["strict_day_accepted"] is True

def test_round_trip_cannot_pass_before_next_open_sell(tmp_path):
    preliminary=AcceptanceFactV51("2026-08-27","2026-08-27T15:20:00+08:00",(),(),"PASS","PASS","PENDING","PENDING","PRELIMINARY_ONLY")
    rt=runtime(tmp_path,"2026-08-28T09:31:10+08:00",mode="REPLAY");rt.store.save("acceptance_facts",preliminary);rt._record("2026-08-27","acceptance",datetime.fromisoformat("2026-08-27T15:20:00+08:00"),"SUCCESS",preliminary.acceptance_id)
    result=rt.run("round_trip_acceptance");assert result["passed"] is False and "next-open exit run" in result["error"]

def test_source_failure_cannot_be_reclassified_as_active_flat(tmp_path):
    preliminary=AcceptanceFactV51("2026-08-27","2026-08-27T15:20:00+08:00",(),(),"PASS","ACTIVE_FLAT","PENDING","PENDING","PRELIMINARY_ONLY")
    rt=runtime(tmp_path,"2026-08-28T09:31:10+08:00",mode="REPLAY");rt.store.save("acceptance_facts",preliminary);rt._record("2026-08-27","acceptance",datetime.fromisoformat("2026-08-27T15:20:00+08:00"),"SUCCESS",preliminary.acceptance_id)
    stage=StageOutcomeFactV51("2026-08-27","execution","ACTIVE_FLAT",("v5.1-baseline-0935-v1","v5.1-closescan-v1"),"2026-08-27T14:50:40+08:00","REPLAY","V51_REPLAY",False);rt.store.save("stage_outcomes",stage)
    failure=ProductionFailureFactV51("2026-08-28","next_open_exit","2026-08-28T09:30:10+08:00","SOURCE_FAILURE","REPLAY","V51_REPLAY",False);rt.store.save("production_failures",failure);rt._record("2026-08-28","next_open_exit",datetime.fromisoformat("2026-08-28T09:30:10+08:00"),"FAILED",failure.failure_id)
    result=rt.run("round_trip_acceptance");assert result["passed"] is False and "next-open exit run" in result["error"]

def test_idempotent_success_fails_closed_if_original_entity_is_tampered(tmp_path):
    rt=runtime(tmp_path,"2026-08-27T14:50:40+08:00");fact=StageOutcomeFactV51("2026-08-27","execution","ACTIVE_FLAT",("v5.1-baseline-0935-v1","v5.1-closescan-v1"),rt.now().isoformat(),rt.mode,rt.cohort,rt.strict_evidence);rt.store.save("stage_outcomes",fact);rt._record("2026-08-27","execution",rt.now(),"SUCCESS",fact.stage_outcome_id)
    path=tmp_path/"stage_outcomes"/"2026-08-27"/f"{fact.stage_outcome_id}.json";row=json.loads(path.read_text(encoding="utf-8"));row["outcome"]="NO_POSITIONS";path.write_text(json.dumps(row),encoding="utf-8")
    with pytest.raises(ContractViolation,match="content-address"):rt.run("execution")
