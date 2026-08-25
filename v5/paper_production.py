"""V5 paper-production projection from final confirmation and native snapshots."""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal,ROUND_DOWN
import json
from pathlib import Path
from .core import ContractViolation
from .market_snapshot import MarketSnapshotV1,QuoteV1
from .paper import PaperLedger,PaperEngine,PaperOrderV1
from .order_quantity import floor_quantity
from .baseline_policy import BASELINE_ID,BASELINE_HASH,assert_runtime_frozen
import hashlib,os

def load_snapshot(path):
    path=Path(path);raw=json.loads(path.read_text(encoding="utf-8"));quotes=[QuoteV1.from_mapping(x) for x in raw["quotes"]]
    snapshot=MarketSnapshotV1.build(trade_date=raw["trade_date"],session=raw["session"],batch_started_at=raw["batch_started_at"],batch_completed_at=raw["batch_completed_at"],quotes=quotes,expected_codes=raw["quality"]["expected_codes"])
    if raw.get("snapshot_id")!=snapshot.snapshot_id or path.stem!=snapshot.snapshot_id:raise ContractViolation("V5 snapshot content-address mismatch")
    return snapshot
class PaperProduction:
    def __init__(self,root):self.root=Path(root);self.ledger=PaperLedger(self.root/"paper");self.engine=PaperEngine(self.ledger)
    def buy(self,confirmation,snapshot,*,at,eligible_sell_date):
        assert_runtime_frozen()
        if confirmation.get("outcome")!="BUY_CANDIDATE" or not confirmation.get("candidates"):raise ContractViolation("final V5 buy candidate required")
        top=confirmation["candidates"][0];quote=next((x for x in snapshot.quotes if x.code==top["code"]),None)
        if not quote or quote.ask1<=0 or quote.ask1_volume<=0:raise ContractViolation("frozen executable ask required")
        order=self.engine.buy_order(decision_id=confirmation["confirmation_id"],code=top["code"],trade_date=confirmation["trade_date"],at=at,ask1=quote.ask1,snapshot_id=snapshot.snapshot_id,eligible_sell_date=eligible_sell_date);depth_shares=floor_quantity(top["code"],quote.ask1_volume)
        if depth_shares<=0:raise ContractViolation("frozen executable ask board lot required")
        if order.shares>depth_shares:order=PaperOrderV1(order.decision_id,order.side,order.code,order.trade_date,order.created_at,order.reference_price,depth_shares,order.snapshot_id,order.eligible_sell_date)
        return self.engine.execute(order,at=at)
    def sell_all(self,snapshot,*,at):
        assert_runtime_frozen()
        events=[]
        for position in list(self.ledger.state()["positions"]):
            quote=next((x for x in snapshot.quotes if x.code==position["code"]),None)
            reference=str(quote.bid1) if quote and quote.bid1>0 else "0"
            order=PaperOrderV1(position["decision_id"],"SELL",position["code"],at.date().isoformat(),at.isoformat(),reference,int(position["shares"]),snapshot.snapshot_id,position["eligible_sell_date"])
            if not quote or quote.bid1<=0:events.append(self.engine.reject(order,"NO_EXECUTABLE_BID",at=at));continue
            if quote.bid1_volume<int(position["shares"]):events.append(self.engine.reject(order,"INSUFFICIENT_BID_DEPTH",at=at));continue
            events.append(self.engine.execute(order,at=at))
        return events
    def save_baseline(self,confirmation,buy_snapshot,sell_snapshot,*,at,decision_snapshot_id=None):
        assert_runtime_frozen()
        rows=[];candidates=list(confirmation.get("candidates",[]))
        if not candidates:raise ContractViolation("baseline confirmed candidates required")
        # Production buys exactly the frozen Top1.  The admission baseline must
        # mirror that exposure instead of diluting it across all confirmations.
        candidates=candidates[:1]
        buy_quotes={quote.code:quote for quote in buy_snapshot.quotes};sell_quotes={quote.code:quote for quote in sell_snapshot.quotes}
        for candidate in candidates:
            buy=buy_quotes.get(candidate["code"]);sell=sell_quotes.get(candidate["code"])
            if not buy or not sell or buy.ask1<=0 or sell.bid1<=0 or buy.ask1_volume<100 or sell.bid1_volume<100:raise ContractViolation("baseline strict executable books required")
            buy_price=Decimal(str(buy.ask1))*(Decimal(1)+self.engine.slippage);sell_price=Decimal(str(sell.bid1))*(Decimal(1)-self.engine.slippage)
            target=self.ledger.initial/Decimal(3);shares=floor_quantity(candidate["code"],(target-self.engine.minimum_commission)/buy_price)
            shares=min(shares,floor_quantity(candidate["code"],buy.ask1_volume),floor_quantity(candidate["code"],sell.bid1_volume))
            if shares<=0:raise ContractViolation("baseline executable board lot required")
            buy_notional=(buy_price*shares).quantize(Decimal("0.01"));sell_notional=(sell_price*shares).quantize(Decimal("0.01"));buy_commission=max(self.engine.minimum_commission,(buy_notional*self.engine.commission_rate).quantize(Decimal("0.01")));sell_commission=max(self.engine.minimum_commission,(sell_notional*self.engine.commission_rate).quantize(Decimal("0.01")));tax=(sell_notional*self.engine.stamp_tax).quantize(Decimal("0.01"));invested=buy_notional+buy_commission;proceeds=sell_notional-sell_commission-tax
            trade_return=float(proceeds/invested-1)
            rows.append({"code":candidate["code"],"shares":shares,"buy_price":float(buy_price),"sell_price":float(sell_price),"buy_commission":float(buy_commission),"sell_commission":float(sell_commission),"stamp_tax":float(tax),"invested":float(invested),"proceeds":float(proceeds),"net_pnl":float(proceeds-invested),"trade_net_return":trade_return,"net_return":trade_return})
        ending=self.ledger.initial-sum((Decimal(str(row["invested"])) for row in rows),Decimal(0))+sum((Decimal(str(row["proceeds"])) for row in rows),Decimal(0))
        net_pnl=ending-self.ledger.initial;invested=sum((Decimal(str(row["invested"])) for row in rows),Decimal(0));trade_return=float(net_pnl/invested) if invested else 0.0
        value={"schema_version":"v5-baseline-round-trip-v2","trade_date":confirmation["trade_date"],"sell_trade_date":at.date().isoformat(),"confirmation_id":confirmation["confirmation_id"],"decision_snapshot_id":decision_snapshot_id or confirmation.get("snapshot_id",buy_snapshot.snapshot_id),"buy_execution_snapshot_id":buy_snapshot.snapshot_id,"sell_execution_snapshot_id":sell_snapshot.snapshot_id,"buy_snapshot_id":buy_snapshot.snapshot_id,"sell_snapshot_id":sell_snapshot.snapshot_id,"baseline_name":"top1_execution_equivalent_next_open","frozen_baseline_id":BASELINE_ID,"frozen_parameter_hash":BASELINE_HASH,"selection_rule":"confirmation_rank_1","initial_cash":float(self.ledger.initial),"invested":float(invested),"net_pnl":float(net_pnl),"trade_net_return":trade_return,"account_net_return":float(net_pnl/self.ledger.initial),"return_basis":"net_pnl_divided_by_invested_capital","constituents":rows,"net_return":trade_return}
        value["baseline_id"]="base1-"+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":" )).encode()).hexdigest()[:24];path=self.root/"paper"/"baselines"/f"{value['baseline_id']}.json";path.parent.mkdir(parents=True,exist_ok=True);raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"));tmp=path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
        try:os.link(tmp,path)
        except FileExistsError:
            if path.read_text(encoding="utf-8")!=raw:raise ContractViolation("baseline immutable collision")
        finally:tmp.unlink(missing_ok=True)
        return value
