"""V5 paper-production projection from final confirmation and native snapshots."""
from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
from .core import ContractViolation
from .market_snapshot import MarketSnapshotV1,QuoteV1
from .paper import PaperLedger,PaperEngine,PaperOrderV1
import hashlib,os

def load_snapshot(path):
    raw=json.loads(Path(path).read_text(encoding="utf-8"));quotes=[QuoteV1.from_mapping(x) for x in raw["quotes"]]
    return MarketSnapshotV1.build(trade_date=raw["trade_date"],session=raw["session"],batch_started_at=raw["batch_started_at"],batch_completed_at=raw["batch_completed_at"],quotes=quotes,expected_codes=raw["quality"]["expected_codes"])
class PaperProduction:
    def __init__(self,root):self.root=Path(root);self.ledger=PaperLedger(self.root/"paper");self.engine=PaperEngine(self.ledger)
    def buy(self,confirmation,snapshot,*,at,eligible_sell_date):
        if confirmation.get("outcome")!="BUY_CANDIDATE" or not confirmation.get("candidates"):raise ContractViolation("final V5 buy candidate required")
        top=confirmation["candidates"][0];quote=next((x for x in snapshot.quotes if x.code==top["code"]),None)
        if not quote or quote.ask1<=0 or quote.ask1_volume<=0:raise ContractViolation("frozen executable ask required")
        order=self.engine.buy_order(decision_id=confirmation["confirmation_id"],code=top["code"],trade_date=confirmation["trade_date"],at=at,ask1=quote.ask1,snapshot_id=snapshot.snapshot_id,eligible_sell_date=eligible_sell_date);depth_shares=int(quote.ask1_volume//100)*100
        if depth_shares<=0:raise ContractViolation("frozen executable ask board lot required")
        if order.shares>depth_shares:order=PaperOrderV1(order.decision_id,order.side,order.code,order.trade_date,order.created_at,order.reference_price,depth_shares,order.snapshot_id,order.eligible_sell_date)
        return self.engine.execute(order,at=at)
    def sell_all(self,snapshot,*,at):
        events=[]
        for position in list(self.ledger.state()["positions"]):
            quote=next((x for x in snapshot.quotes if x.code==position["code"]),None)
            if not quote or quote.bid1<=0 or quote.bid1_volume<int(position["shares"]):continue
            order=PaperOrderV1(position["decision_id"],"SELL",position["code"],at.date().isoformat(),at.isoformat(),str(quote.bid1),int(position["shares"]),snapshot.snapshot_id,position["eligible_sell_date"]);events.append(self.engine.execute(order,at=at))
        return events
    def save_baseline(self,confirmation,buy_snapshot,sell_snapshot,*,at):
        rows=[]
        buy_quotes={quote.code:quote for quote in buy_snapshot.quotes};sell_quotes={quote.code:quote for quote in sell_snapshot.quotes}
        for candidate in confirmation.get("candidates",[]):
            buy=buy_quotes.get(candidate["code"]);sell=sell_quotes.get(candidate["code"])
            if not buy or not sell or buy.ask1<=0 or sell.bid1<=0:raise ContractViolation("baseline strict executable books required")
            buy_price=buy.ask1*(1+float(self.engine.slippage));sell_price=sell.bid1*(1-float(self.engine.slippage));rows.append({"code":candidate["code"],"buy_price":buy_price,"sell_price":sell_price,"net_return":sell_price/buy_price-1})
        value={"schema_version":"v5-baseline-round-trip-v1","trade_date":confirmation["trade_date"],"sell_trade_date":at.date().isoformat(),"confirmation_id":confirmation["confirmation_id"],"buy_snapshot_id":buy_snapshot.snapshot_id,"sell_snapshot_id":sell_snapshot.snapshot_id,"baseline_name":"equal_weight_confirmed_next_open","constituents":rows,"net_return":sum(row["net_return"] for row in rows)/len(rows) if rows else None}
        value["baseline_id"]="base1-"+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":" )).encode()).hexdigest()[:24];path=self.root/"paper"/"baselines"/f"{value['baseline_id']}.json";path.parent.mkdir(parents=True,exist_ok=True);raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"));tmp=path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
        try:os.link(tmp,path)
        except FileExistsError:
            if path.read_text(encoding="utf-8")!=raw:raise ContractViolation("baseline immutable collision")
        finally:tmp.unlink(missing_ok=True)
        return value
