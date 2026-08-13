from datetime import datetime,timedelta
from tempfile import TemporaryDirectory
from v5.core import CHINA_TZ
from v5.market_snapshot import QuoteV1,MarketSnapshotV1
from v5.paper_production import PaperProduction,load_snapshot
from v5.storage import V5FactStore
import pytest,json
NOW=datetime(2026,8,14,14,50,tzinfo=CHINA_TZ)
def snapshot(at,session,price):
 q=QuoteV1.from_mapping({"code":"000001","name":"测试","trade_date":at.date().isoformat(),"exchange_time":at-timedelta(seconds=1),"provider_time":at-timedelta(seconds=1),"received_at":at,"last_price":price,"previous_close":10,"open_price":10,"high_price":price,"low_price":9.9,"bid1":price-.01,"bid1_volume":10000,"ask1":price+.01,"ask1_volume":10000,"volume":100000,"amount":8000000,"halted":False,"limit_up":False,"limit_down":False,"provider":"test"});return MarketSnapshotV1.build(trade_date=at.date().isoformat(),session=session,batch_started_at=at-timedelta(seconds=2),batch_completed_at=at,quotes=[q],expected_codes=1)
def test_production_adapter_uses_only_final_v5_confirmation_and_reconciles():
 with TemporaryDirectory() as d:
  p=PaperProduction(d);confirmation={"outcome":"BUY_CANDIDATE","confirmation_id":"v5cd1-test","trade_date":"2026-08-14","candidates":[{"code":"000001"}]};buy=p.buy(confirmation,snapshot(NOW,"buy",10.2),at=NOW,eligible_sell_date="2026-08-17");assert buy.outcome=="FILLED"
  sell_at=datetime(2026,8,17,9,30,tzinfo=CHINA_TZ);events=p.sell_all(snapshot(sell_at,"sell",10.4),at=sell_at);assert events[0].outcome=="FILLED" and p.ledger.reconcile()["passed"]
  baseline=p.save_baseline({**confirmation,"candidates":[{"code":"000001"}]},snapshot(NOW,"buy",10.2),snapshot(sell_at,"sell",10.4),at=sell_at);assert baseline["baseline_name"]=="top1_execution_equivalent_next_open" and baseline["selection_rule"]=="confirmation_rank_1" and baseline["net_return"] is not None and list((p.root/"paper/baselines").glob("*.json"))
  row=baseline["constituents"][0];assert row["shares"]%100==0 and row["buy_commission"]>=5 and row["sell_commission"]>=5 and row["stamp_tax"]>0 and baseline["net_return"]<row["sell_price"]/row["buy_price"]-1

def test_admission_baseline_matches_production_top1_exposure():
 with TemporaryDirectory() as d:
  p=PaperProduction(d);sell_at=datetime(2026,8,17,9,30,tzinfo=CHINA_TZ);buy=snapshot(NOW,"buy",10.2);sell=snapshot(sell_at,"sell",10.4)
  confirmation={"confirmation_id":"v5cd1-top1","trade_date":"2026-08-14","candidates":[{"code":"000001","rank":1},{"code":"000002","rank":2}]}
  baseline=p.save_baseline(confirmation,buy,sell,at=sell_at)
  assert [row["code"] for row in baseline["constituents"]]==["000001"]

def test_paper_buy_is_capped_by_frozen_ask_depth_and_sell_requires_full_bid_depth():
 with TemporaryDirectory() as d:
  p=PaperProduction(d);confirmation={"outcome":"BUY_CANDIDATE","confirmation_id":"v5cd1-depth","trade_date":"2026-08-14","candidates":[{"code":"000001"}]};buy_snapshot=snapshot(NOW,"buy",10.2);quote=buy_snapshot.quotes[0];limited=MarketSnapshotV1.build(trade_date=buy_snapshot.trade_date,session="buy",batch_started_at=NOW-timedelta(seconds=2),batch_completed_at=NOW,quotes=[QuoteV1.from_mapping({**quote.__dict__,"ask1_volume":500})],expected_codes=1);event=p.buy(confirmation,limited,at=NOW,eligible_sell_date="2026-08-17");assert event.shares==500
  sell_at=datetime(2026,8,17,9,30,tzinfo=CHINA_TZ);sell_snapshot=snapshot(sell_at,"sell",10.4);q=sell_snapshot.quotes[0];thin=MarketSnapshotV1.build(trade_date=sell_snapshot.trade_date,session="sell",batch_started_at=sell_at-timedelta(seconds=2),batch_completed_at=sell_at,quotes=[QuoteV1.from_mapping({**q.__dict__,"bid1_volume":100})],expected_codes=1);events=p.sell_all(thin,at=sell_at);assert events[0].outcome=="REJECTED" and events[0].reason=="INSUFFICIENT_BID_DEPTH" and p.ledger.state()["positions"]

def test_snapshot_reader_verifies_declared_id_rebuilt_hash_and_filename(tmp_path):
 snap=snapshot(NOW,"buy",10.2);path=V5FactStore(tmp_path).save_snapshot(snap);assert load_snapshot(path).snapshot_id==snap.snapshot_id
 renamed=path.with_name("ms1-wrong.json");renamed.write_bytes(path.read_bytes())
 with pytest.raises(Exception,match="content-address mismatch"):load_snapshot(renamed)
 raw=json.loads(path.read_text(encoding="utf-8"));raw["quotes"][0]["last_price"]=11;path.write_text(json.dumps(raw),encoding="utf-8")
 with pytest.raises(Exception,match="content-address mismatch"):load_snapshot(path)
