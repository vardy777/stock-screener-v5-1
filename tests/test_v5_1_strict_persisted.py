import json
from datetime import datetime

import pytest

from shared_core.core import CHINA_TZ,ContractViolation
from shared_core.market_snapshot import QuoteV1
from shared_core.market_state import MarketStateV1
from shared_core.paper import PaperLedger
from shared_core.contracts import AcquisitionSessionV1,CandidateFunnelV1
from shared_core.market_snapshot import MarketSnapshotV1
from v5_1.facts import content_id
from v5_1.production_read_model import ImmutableReadModelBuilder,ProductionRunFactV51
from v5_1.security_master import SecurityMasterVersionV1,MasterVerificationV1
from v5_1.master_evidence import DirectoryResponseFactV51,MasterMatchFactV51
from v5_1.execution import ExecutionObservationV51
import base64,hashlib

NOW="2026-08-28T14:50:40+08:00"

def quote(**overrides):
    row={"code":"600000","name":"浦发银行","trade_date":"2026-08-28","exchange_time":NOW,"provider_time":NOW,"received_at":NOW,"last_price":10.0,"previous_close":9.9,"open_price":9.95,"high_price":10.1,"low_price":9.8,"bid1":9.99,"bid1_volume":1000,"ask1":10.01,"ask1_volume":1000,"volume":10000,"amount":100000.0,"halted":False,"limit_up":False,"limit_down":False,"provider":"test"};row.update(overrides);return row

@pytest.mark.parametrize("bad",["true","false",1,0,None,[],{}])
def test_quote_boolean_is_strict(bad):
    with pytest.raises(ContractViolation,match="strict boolean"):QuoteV1.from_mapping(quote(halted=bad))

@pytest.mark.parametrize("field,bad",[("bid1_volume","1000"),("amount","100000"),("volume",True)])
def test_quote_numeric_types_are_strict(field,bad):
    with pytest.raises(ContractViolation):QuoteV1.from_mapping(quote(**{field:bad}))

def test_market_state_rejects_string_boolean_and_extra_key():
    row={"trade_date":"2026-08-28","snapshot_id":"ms1-x","total":1,"advancers":1,"decliners":0,"unchanged":0,"limit_up":0,"limit_down":0,"halted":0,"total_amount":1.0,"median_change":0.01,"advance_ratio":1.0,"severe_decline_ratio":0.0,"regime":"STRONG","trade_allowed":"false","reasons":[],"policy_version":"v5-market-state-policy-v1","schema_version":"v5-market-state-v1","market_state_id":"x"}
    with pytest.raises(ContractViolation,match="strict boolean"):MarketStateV1.from_mapping(row)
    row["trade_allowed"]=False;row["unexpected"]=1
    with pytest.raises(ContractViolation,match="keys invalid"):MarketStateV1.from_mapping(row)

def test_read_model_quarantines_extra_persisted_key(tmp_path):
    fact=ProductionRunFactV51("2026-08-28","acceptance",NOW,"SUCCESS","x")
    row=fact.to_dict();row["unexpected"]=True;row["run_id"]=content_id("v51prodrun1",{k:v for k,v in row.items() if k!="run_id"})
    folder=tmp_path/"production_runs"/"2026-08-28";folder.mkdir(parents=True);(folder/f"{row['run_id']}.json").write_text(json.dumps(row),encoding="utf-8")
    model=ImmutableReadModelBuilder(tmp_path).build("2026-08-28",as_of=datetime(2026,8,28,15,30,tzinfo=CHINA_TZ))
    assert model.state=="FAIL_CLOSED" and model.health["lineage"]=="QUARANTINED"

def test_paper_reader_rejects_string_share_count(tmp_path):
    event={"order_id":"o","outcome":"FILLED","reason":"FILLED","recorded_at":NOW,"code":"600000","side":"BUY","shares":"100","fill_price":"10","commission":"5","tax":"0","cash_flow":"-1005","decision_id":"d","trade_date":"2026-08-28","eligible_sell_date":"2026-08-29","schema_version":"v5-paper-event-v1"}
    payload={"schema_version":"v5-paper-ledger-v1","initial_cash":"100000","head":"forged","events":[{"sequence":1,"previous_event_id":"genesis","event_id":"forged","event":event}]};tmp_path.mkdir(exist_ok=True);(tmp_path/"events.json").write_text(json.dumps(payload),encoding="utf-8")
    with pytest.raises(ContractViolation,match="strict integer"):PaperLedger(tmp_path).events()

@pytest.mark.parametrize("bad",["true","false",1,0,None,[],{}])
def test_acquisition_session_canonical_boolean_is_strict(bad):
    with pytest.raises(ContractViolation,match="strict boolean"):
        AcquisitionSessionV1.build(trade_date="2026-08-28",stage="morning",requested_at=NOW,expected_codes=1,selected_snapshot_id="",accepted=bad,source_attempts=[{"source":"test"}])

@pytest.mark.parametrize("bad",["1",1.0,True,None])
def test_acquisition_session_expected_codes_is_strict_integer(bad):
    with pytest.raises(ContractViolation,match="strict integer"):
        AcquisitionSessionV1.build(trade_date="2026-08-28",stage="morning",requested_at=NOW,expected_codes=bad,selected_snapshot_id="",accepted=False,source_attempts=[{"source":"test"}])

@pytest.mark.parametrize("bad",["true","false",1,0,None,[],{}])
def test_candidate_funnel_canonical_boolean_is_strict(bad):
    snapshot=MarketSnapshotV1.build(trade_date="2026-08-28",session="morning",batch_started_at=NOW,batch_completed_at=NOW,quotes=[QuoteV1.from_mapping(quote())],expected_codes=1)
    with pytest.raises(ContractViolation,match="strict boolean"):
        CandidateFunnelV1.build(snapshot=snapshot,market_state_id="mstate1-test",stage="morning",accepted=bad,policy_version="policy-v1",stages=[{"name":"eligible"}],candidates=[])

def test_candidate_funnel_rejects_non_string_code_and_wrong_enum():
    snapshot=MarketSnapshotV1.build(trade_date="2026-08-28",session="morning",batch_started_at=NOW,batch_completed_at=NOW,quotes=[QuoteV1.from_mapping(quote())],expected_codes=1)
    with pytest.raises(ContractViolation,match="strict string"):
        CandidateFunnelV1.build(snapshot=snapshot,market_state_id="mstate1-test",stage="morning",accepted=True,policy_version="policy-v1",stages=[{"name":"eligible"}],candidates=[{"code":600000}])
    with pytest.raises(ContractViolation,match="unsupported value"):
        CandidateFunnelV1.build(snapshot=snapshot,market_state_id="mstate1-test",stage="unknown",accepted=True,policy_version="policy-v1",stages=[{"name":"eligible"}],candidates=[])

@pytest.mark.parametrize("bad",["1",1.0,True,None])
def test_master_verification_record_count_is_strict_integer(bad):
    with pytest.raises(ContractViolation,match="strict integer"):
        MasterVerificationV1.build(verified_for_trade_date="2026-08-28",verified_at=NOW,source_families=["sse"],independent_source_families=["sse"],master_version_ids=["smv1-x"],record_count=bad)

@pytest.mark.parametrize("field,bad",[("symbol",600000),("exchange",1),("board",True),("security_name",123),("source_family",1),("source_record_id",False)])
def test_security_master_identity_strings_are_strict(field,bad):
    row={"symbol":"600000","exchange":"SSE","board":"MAIN","security_name":"浦发银行","listing_date":"1999-11-10","known_at":NOW,"source_family":"sse","source_record_id":"sse-600000"};row[field]=bad
    with pytest.raises(ContractViolation,match="strict string"):
        SecurityMasterVersionV1.build(**row)

def test_directory_response_metadata_strings_are_strict():
    raw=b"[]";row={"provider_family":"sse","exchange":"SSE","endpoint":"https://example.invalid","retrieved_at":NOW,"raw_sha256":hashlib.sha256(raw).hexdigest(),"raw_content_b64":base64.b64encode(raw).decode(),"record_count":0}
    for field,bad in (("provider_family",1),("exchange",True),("endpoint",None),("raw_sha256",123),("raw_content_b64",False)):
        changed={**row,field:bad}
        with pytest.raises(ContractViolation):DirectoryResponseFactV51.build(**changed)

def test_execution_observation_identity_does_not_coerce_types():
    row={"trade_date":"2026-08-28","side":"BUY","strategy_id":"s","decision_id":"d","decision_snapshot_id":"ms1-d","decision_time":NOW,"execution_snapshot_id":"ms1-e","execution_observation_time":NOW,"execution_time":NOW,"code":"600000","bid1":9.9,"bid1_volume":100,"ask1":10.0,"ask1_volume":100}
    for field,bad in (("side",1),("strategy_id",True),("decision_id",1),("decision_snapshot_id",None),("code",600000)):
        with pytest.raises(ContractViolation):ExecutionObservationV51(**{**row,field:bad})
