"""Deterministic frozen V5 end-to-end replay."""
from __future__ import annotations
from .data_production import ConsensusAcquirer
from .funnel import CandidateFunnel
from .decision_flow import MorningPoolV5,ConfirmationV5
from .paper import PaperEngine,PaperOrderV1
from .performance import report_strict_paper

def replay(*,universe,morning_sources,confirmation_sources,morning_at,confirmation_at,sell_snapshot,sell_at,ledger):
    morning=ConsensusAcquirer(*morning_sources).acquire(universe,stage="morning",now=morning_at)
    if not morning.accepted:return {"status":"REJECTED","stage":"morning_consensus","report":morning.report}
    funnel=CandidateFunnel();mf=funnel.run(morning.primary,market_state_id="mstate1-replay-morning",market_valid=True,stage="morning");pool=MorningPoolV5.from_funnel(mf,created_at=morning_at)
    confirm=ConsensusAcquirer(*confirmation_sources).acquire(universe,stage="confirmation",now=confirmation_at)
    if not confirm.accepted:return {"status":"REJECTED","stage":"confirmation_consensus","report":confirm.report}
    cf=funnel.run(confirm.primary,market_state_id="mstate1-replay-confirm",market_valid=True,stage="confirmation",allowed_codes=[x["code"] for x in pool.candidates]);decision=ConfirmationV5.from_funnel(pool,cf,decided_at=confirmation_at)
    if not decision.candidates:return {"status":"NO_TRADE","pool_id":pool.pool_id,"confirmation_id":decision.confirmation_id}
    top=decision.candidates[0];quote=next(x for x in confirm.primary.quotes if x.code==top["code"]);engine=PaperEngine(ledger);buy=engine.buy_order(decision_id=decision.confirmation_id,code=top["code"],trade_date=universe.trade_date,at=confirmation_at,ask1=quote.ask1,snapshot_id=confirm.primary.snapshot_id,eligible_sell_date=sell_at.date().isoformat());buy_event=engine.execute(buy,at=confirmation_at)
    sell_quote=next(x for x in sell_snapshot.quotes if x.code==top["code"]);sell=PaperOrderV1(decision.confirmation_id,"SELL",top["code"],sell_at.date().isoformat(),sell_at.isoformat(),str(sell_quote.bid1),buy.shares,sell_snapshot.snapshot_id,sell_at.date().isoformat());sell_event=engine.execute(sell,at=sell_at)
    round_trip={"net_return":float((float(sell_event.cash_flow)+float(buy_event.cash_flow))/-float(buy_event.cash_flow)),"net_pnl":float(sell_event.cash_flow)+float(buy_event.cash_flow)}
    return {"status":"COMPLETED","pool_id":pool.pool_id,"confirmation_id":decision.confirmation_id,"buy_event_id":buy_event.event_id,"sell_event_id":sell_event.event_id,"reconciliation":ledger.reconcile(),"performance":report_strict_paper([round_trip],minimum_trades=40).to_dict()}
