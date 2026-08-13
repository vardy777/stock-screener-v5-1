"""V5 paper-production projection from final confirmation and native snapshots."""
from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
from .core import ContractViolation
from .market_snapshot import MarketSnapshotV1,QuoteV1
from .paper import PaperLedger,PaperEngine,PaperOrderV1

def load_snapshot(path):
    raw=json.loads(Path(path).read_text(encoding="utf-8"));quotes=[QuoteV1.from_mapping(x) for x in raw["quotes"]]
    return MarketSnapshotV1.build(trade_date=raw["trade_date"],session=raw["session"],batch_started_at=raw["batch_started_at"],batch_completed_at=raw["batch_completed_at"],quotes=quotes,expected_codes=raw["quality"]["expected_codes"])
class PaperProduction:
    def __init__(self,root):self.root=Path(root);self.ledger=PaperLedger(self.root/"paper");self.engine=PaperEngine(self.ledger)
    def buy(self,confirmation,snapshot,*,at,eligible_sell_date):
        if confirmation.get("outcome")!="BUY_CANDIDATE" or not confirmation.get("candidates"):raise ContractViolation("final V5 buy candidate required")
        top=confirmation["candidates"][0];quote=next((x for x in snapshot.quotes if x.code==top["code"]),None)
        if not quote or quote.ask1<=0 or quote.ask1_volume<=0:raise ContractViolation("frozen executable ask required")
        order=self.engine.buy_order(decision_id=confirmation["confirmation_id"],code=top["code"],trade_date=confirmation["trade_date"],at=at,ask1=quote.ask1,snapshot_id=snapshot.snapshot_id,eligible_sell_date=eligible_sell_date);return self.engine.execute(order,at=at)
    def sell_all(self,snapshot,*,at):
        events=[]
        for position in list(self.ledger.state()["positions"]):
            quote=next((x for x in snapshot.quotes if x.code==position["code"]),None)
            if not quote or quote.bid1<=0 or quote.bid1_volume<=0:continue
            order=PaperOrderV1(position["decision_id"],"SELL",position["code"],at.date().isoformat(),at.isoformat(),str(quote.bid1),int(position["shares"]),snapshot.snapshot_id,position["eligible_sell_date"]);events.append(self.engine.execute(order,at=at))
        return events
