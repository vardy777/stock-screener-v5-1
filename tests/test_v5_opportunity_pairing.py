from datetime import datetime
from v5.core import CHINA_TZ
from v5.opportunity import save_opportunity,save_pairing,load_pairs

NOW=datetime(2026,8,25,14,50,40,tzinfo=CHINA_TZ)
def opportunity(root,**changes):
    args={"trade_date":"2026-08-25","created_at":NOW.isoformat(),"morning_pool_id":"pool","morning_observed_at":"2026-08-25T09:25:10+08:00","decision_snapshot_id":"decision","decision_snapshot_at":"2026-08-25T14:49:10+08:00","confirmation_at":"2026-08-25T14:50:10+08:00","baseline_confirmation_id":"base","challenger_confirmation_id":"challenge","baseline_code":"","challenger_code":"","buy_execution_snapshot_id":"","buy_execution_at":"","market_regime":"NEUTRAL","turnover_regime":"NORMAL","large_index_decline":False};args.update(changes);return save_opportunity(root,**args)

def test_double_empty_is_an_eligible_zero_zero_opportunity_day(tmp_path):
    row=opportunity(tmp_path);pair=save_pairing(tmp_path,row,recorded_at="2026-08-26T09:30:10+08:00",sell_execution_snapshot_id="",baseline_return=0,challenger_return=0,baseline_traded=False,challenger_traded=False)
    assert row["eligible"] is True and pair["eligible"] is True and pair["baseline_return"]==pair["challenger_return"]==0 and len(load_pairs(tmp_path))==1

def test_single_side_trade_requires_shared_buy_and_sell_window_lineage(tmp_path):
    missing=opportunity(tmp_path,challenger_code="000001",buy_execution_snapshot_id="")
    rejected=save_pairing(tmp_path,missing,recorded_at="2026-08-26T09:30:10+08:00",sell_execution_snapshot_id="",baseline_return=0,challenger_return=.01,baseline_traded=False,challenger_traded=True);assert rejected["eligible"] is False
    valid=opportunity(tmp_path,trade_date="2026-08-26",morning_observed_at="2026-08-26T09:25:10+08:00",decision_snapshot_at="2026-08-26T14:49:10+08:00",confirmation_at="2026-08-26T14:50:10+08:00",challenger_code="000001",buy_execution_snapshot_id="buy-shared",buy_execution_at="2026-08-26T14:50:40+08:00")
    accepted=save_pairing(tmp_path,valid,recorded_at="2026-08-27T09:30:10+08:00",sell_execution_snapshot_id="sell-shared",baseline_return=0,challenger_return=.01,baseline_traded=False,challenger_traded=True);assert accepted["eligible"] is True
