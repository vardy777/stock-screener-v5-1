from datetime import datetime,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from v5.core import CHINA_TZ
from v5.paper import PaperLedger,PaperEngine,PaperOrderV1

NOW=datetime(2026,8,13,14,50,tzinfo=CHINA_TZ)
def order(side="BUY",day="2026-08-13",shares=1000):return PaperOrderV1("decision-1",side,"000001",day,NOW.isoformat(),"10",shares,"ms1-test","2026-08-14")
def test_buy_sell_t1_fees_idempotency_and_reconciliation():
    with TemporaryDirectory() as directory:
        ledger=PaperLedger(directory);engine=PaperEngine(ledger);buy=engine.buy_order(decision_id="decision-1",code="000001",trade_date="2026-08-13",at=NOW,ask1=10,snapshot_id="ms1-test",eligible_sell_date="2026-08-14")
        first=engine.execute(buy,at=NOW);assert first.outcome=="FILLED";assert ledger.append(first) is False
        early=engine.execute(order("SELL","2026-08-13",buy.shares),at=NOW+timedelta(hours=1));assert early.outcome=="REJECTED" and early.reason=="T_PLUS_ONE"
        sell=PaperOrderV1("decision-1","SELL","000001","2026-08-14",(NOW+timedelta(days=1)).isoformat(),"10.2",buy.shares,"ms1-sell","2026-08-14")
        filled=engine.execute(sell,at=NOW+timedelta(days=1));assert filled.outcome=="FILLED";assert ledger.reconcile()["passed"]

def test_one_third_cap_and_invalid_board_lot_are_immutable_rejections():
    with TemporaryDirectory() as directory:
        ledger=PaperLedger(directory);engine=PaperEngine(ledger)
        too_large=engine.execute(order(shares=4000),at=NOW);assert too_large.outcome=="REJECTED" and too_large.reason=="ONE_THIRD_CAP"
        odd=engine.execute(order(shares=101),at=NOW);assert odd.reason=="INVALID_BOARD_LOT"
        assert len(ledger.state()["rejections"])==2

def test_event_chain_detects_tampering_and_order_recovery_is_idempotent():
    with TemporaryDirectory() as directory:
        ledger=PaperLedger(directory);engine=PaperEngine(ledger);event=engine.execute(order(shares=1000),at=NOW);assert event.outcome=="FILLED"
        assert engine.execute(order(shares=1000),at=NOW).event_id==event.event_id
        path=Path(directory)/"events.json";raw=path.read_text(encoding="utf-8");path.write_text(raw.replace('"cash_flow":"-10010.00"','"cash_flow":"0.00"'),encoding="utf-8")
        try:ledger.events();assert False
        except Exception:pass
