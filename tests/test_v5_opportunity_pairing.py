from datetime import datetime
import json
from v5.core import CHINA_TZ
from v5.opportunity import save_opportunity,save_pairing,load_pairs,save_sell_observation

NOW=datetime(2026,8,25,14,50,40,tzinfo=CHINA_TZ)
def opportunity(root,**changes):
    args={"trade_date":"2026-08-25","created_at":NOW.isoformat(),"morning_pool_id":"pool","morning_observed_at":"2026-08-25T09:25:10+08:00","decision_snapshot_id":"decision","decision_snapshot_at":"2026-08-25T14:49:10+08:00","confirmation_at":"2026-08-25T14:50:10+08:00","baseline_confirmation_id":"base","challenger_confirmation_id":"challenge","baseline_code":"","challenger_code":"","buy_execution_snapshot_id":"","buy_execution_at":"","market_regime":"NEUTRAL","turnover_regime":"NORMAL","large_index_decline":False};args.update(changes);return save_opportunity(root,**args)

def test_double_empty_is_an_eligible_zero_zero_opportunity_day(tmp_path):
    row=opportunity(tmp_path);observation=save_sell_observation(tmp_path,trade_date="2026-08-26",observed_at="2026-08-26T09:30:10+08:00",snapshot_id="",codes=[]);pair=save_pairing(tmp_path,row,recorded_at="2026-08-26T09:30:10+08:00",sell_execution_snapshot_id="",sell_observation_id=observation["observation_id"],baseline_return=0,challenger_return=0,baseline_traded=False,challenger_traded=False,lineage_valid=True)
    assert row["eligible"] is True and pair["eligible"] is True and pair["baseline_return"]==pair["challenger_return"]==0 and len(load_pairs(tmp_path))==1

def test_breadth_proxy_cannot_mark_large_index_decline_without_index_fact(tmp_path):
    row=opportunity(tmp_path,large_index_decline=True,index_decline_status="UNKNOWN",index_benchmark_id="")
    assert row["large_index_decline"] is False and row["index_decline_status"]=="UNKNOWN"

def test_single_side_trade_requires_shared_buy_and_sell_window_lineage(tmp_path):
    missing=opportunity(tmp_path,challenger_code="000001",buy_execution_snapshot_id="")
    rejected=save_pairing(tmp_path,missing,recorded_at="2026-08-26T09:30:10+08:00",sell_execution_snapshot_id="",sell_observation_id="",baseline_return=0,challenger_return=.01,baseline_traded=False,challenger_traded=True,lineage_valid=False);assert rejected["eligible"] is False
    valid=opportunity(tmp_path,trade_date="2026-08-26",morning_observed_at="2026-08-26T09:25:10+08:00",decision_snapshot_at="2026-08-26T14:49:10+08:00",confirmation_at="2026-08-26T14:50:10+08:00",challenger_code="000001",buy_execution_snapshot_id="buy-shared",buy_execution_at="2026-08-26T14:50:40+08:00")
    accepted=save_pairing(tmp_path,valid,recorded_at="2026-08-27T09:30:10+08:00",sell_execution_snapshot_id="sell-shared",sell_observation_id="",baseline_return=0,challenger_return=.01,baseline_traded=False,challenger_traded=True,lineage_valid=True);assert accepted["eligible"] is True

def test_tampered_pairing_or_referenced_opportunity_is_quarantined(tmp_path):
    row=opportunity(tmp_path);obs=save_sell_observation(tmp_path,trade_date="2026-08-26",observed_at="2026-08-26T09:30:10+08:00",snapshot_id="",codes=[])
    pair=save_pairing(tmp_path,row,recorded_at=obs["observed_at"],sell_execution_snapshot_id="",sell_observation_id=obs["observation_id"],baseline_return=0,challenger_return=0,baseline_traded=False,challenger_traded=False,lineage_valid=True)
    pair_path=tmp_path/"pairings/2026-08-25"/f"{pair['pairing_id']}.json";raw=json.loads(pair_path.read_text(encoding="utf-8"));raw["challenger_return"]=9;pair_path.write_text(json.dumps(raw),encoding="utf-8")
    loaded=load_pairs(tmp_path);assert loaded[0]["eligible"] is False and "hash mismatch" in loaded[0]["evidence_error"]
