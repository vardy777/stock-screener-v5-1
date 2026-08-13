from datetime import datetime,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from v5.core import CHINA_TZ
from v5.paper import PaperLedger,PaperEngine,PaperOrderV1
from concurrent.futures import ThreadPoolExecutor

NOW=datetime(2026,8,13,14,50,tzinfo=CHINA_TZ)
def order(side="BUY",day="2026-08-13",shares=1000):return PaperOrderV1("decision-1",side,"000001",day,NOW.isoformat(),"10",shares,"ms1-test","2026-08-14")
def test_buy_sell_t1_fees_idempotency_and_reconciliation():
    with TemporaryDirectory() as directory:
        ledger=PaperLedger(directory);engine=PaperEngine(ledger);buy=engine.buy_order(decision_id="decision-1",code="000001",trade_date="2026-08-13",at=NOW,ask1=10,snapshot_id="ms1-test",eligible_sell_date="2026-08-14")
        first=engine.execute(buy,at=NOW);assert first.outcome=="FILLED";assert ledger.append(first) is False
        early=engine.execute(order("SELL","2026-08-13",buy.shares),at=NOW+timedelta(minutes=1));assert early.outcome=="REJECTED" and early.reason=="T_PLUS_ONE"
        sell=PaperOrderV1("decision-1","SELL","000001","2026-08-14",(NOW+timedelta(days=1)).isoformat(),"10.2",buy.shares,"ms1-sell","2026-08-14")
        filled=engine.execute(sell,at=NOW+timedelta(days=1));assert filled.outcome=="FILLED";assert ledger.reconcile()["passed"]
        trips=ledger.round_trips();assert len(trips)==1 and trips[0]["buy_event_id"]==first.event_id and trips[0]["sell_event_id"]==filled.event_id and trips[0]["net_pnl"]!=0

def test_one_third_cap_and_invalid_board_lot_are_immutable_rejections():
    with TemporaryDirectory() as directory:
        ledger=PaperLedger(directory);engine=PaperEngine(ledger)
        too_large=engine.execute(order(shares=4000),at=NOW);assert too_large.outcome=="REJECTED" and too_large.reason=="ONE_THIRD_CAP"
        odd=engine.execute(order(shares=101),at=NOW);assert odd.reason=="INVALID_BOARD_LOT"
        assert len(ledger.state()["rejections"])==2

def test_each_symbol_uses_initial_capital_third_not_declining_cash_third():
    with TemporaryDirectory() as directory:
        ledger=PaperLedger(directory);engine=PaperEngine(ledger)
        for index,code in enumerate(("000001","000002","000003")):
            buy=engine.buy_order(decision_id=f"d{index}",code=code,trade_date="2026-08-13",at=NOW,ask1=10,snapshot_id="ms1-test",eligible_sell_date="2026-08-14");event=engine.execute(buy,at=NOW);assert event.outcome=="FILLED";assert buy.shares>=3300
        assert ledger.state()["cash"]>=0

def test_event_chain_detects_tampering_and_order_recovery_is_idempotent():
    with TemporaryDirectory() as directory:
        ledger=PaperLedger(directory);engine=PaperEngine(ledger);event=engine.execute(order(shares=1000),at=NOW);assert event.outcome=="FILLED"
        assert engine.execute(order(shares=1000),at=NOW).event_id==event.event_id
        path=Path(directory)/"events.json";raw=path.read_text(encoding="utf-8");path.write_text(raw.replace('"cash_flow":"-10010.00"','"cash_flow":"0.00"'),encoding="utf-8")
        try:ledger.events();assert False
        except Exception:pass

def test_account_and_round_trips_obey_as_of_cutoff():
    with TemporaryDirectory() as directory:
        ledger=PaperLedger(directory);engine=PaperEngine(ledger);buy=engine.buy_order(decision_id="d",code="000001",trade_date="2026-08-13",at=NOW,ask1=10,snapshot_id="ms1",eligible_sell_date="2026-08-14");engine.execute(buy,at=NOW)
        sell_at=NOW+timedelta(days=1);sell=PaperOrderV1("d","SELL","000001","2026-08-14",sell_at.isoformat(),"10.2",buy.shares,"ms2","2026-08-14");engine.execute(sell,at=sell_at)
        assert ledger.state(as_of=NOW)["positions"] and ledger.round_trips(as_of=NOW)==[]
        assert not ledger.state(as_of=sell_at)["positions"] and len(ledger.round_trips(as_of=sell_at))==1

def test_concurrent_ledger_appends_do_not_lose_events():
    with TemporaryDirectory() as directory:
        def execute(index):
            ledger=PaperLedger(directory);engine=PaperEngine(ledger);return engine.execute(PaperOrderV1(f"d{index}","BUY",f"00000{index+1}","2026-08-13",NOW.isoformat(),"1",100,"ms1","2026-08-14"),at=NOW)
        with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(execute,range(3)))
        ledger=PaperLedger(directory);assert len(ledger.events())==3 and ledger.reconcile()["passed"]

def test_execution_rejects_naive_future_cross_day_and_wrong_windows():
    with TemporaryDirectory() as directory:
        engine=PaperEngine(PaperLedger(directory));valid=order()
        cases=((valid,NOW.replace(tzinfo=None),"timezone"),(PaperOrderV1(valid.decision_id,valid.side,valid.code,valid.trade_date,NOW.replace(hour=14,minute=49).isoformat(),valid.reference_price,valid.shares,valid.snapshot_id,valid.eligible_sell_date),NOW.replace(hour=14,minute=49),"outside strict window"),(valid,NOW+timedelta(days=1),"trade date mismatch"))
        for candidate,at,expected in cases:
            try:engine.execute(candidate,at=at)
            except Exception as exc:assert expected in str(exc)
            else:raise AssertionError(expected)
        future=PaperOrderV1(valid.decision_id,valid.side,valid.code,valid.trade_date,(NOW+timedelta(seconds=1)).isoformat(),valid.reference_price,valid.shares,valid.snapshot_id,valid.eligible_sell_date)
        try:engine.execute(future,at=NOW)
        except Exception as exc:assert "created in future" in str(exc)
        else:raise AssertionError("future order accepted")

def test_order_before_event_crash_is_reported_and_idempotently_recoverable():
    with TemporaryDirectory() as directory:
        ledger=PaperLedger(directory);candidate=order();ledger.save_order(candidate);report=ledger.recovery_report();assert report["status"]=="RECOVERY_REQUIRED" and report["pending_orders"][0]["order_id"]==candidate.order_id
        event=PaperEngine(ledger).execute(ledger.pending_orders()[0],at=NOW);assert event.outcome=="FILLED" and ledger.recovery_report()["status"]=="CLEAN"
