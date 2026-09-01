"""Post-decision executable quote facts shared by V5.1 strategies."""
from __future__ import annotations
from dataclasses import asdict,dataclass
from datetime import datetime
from shared_core.core import ContractViolation,strict_int,strict_number,strict_str,strict_enum
from shared_core.market_snapshot import MarketSnapshotV1
from . import CONTRACT_VERSION,SYSTEM_VERSION
from .facts import content_id
from .security_master import aware
from shared_core.paper import PaperEngine,PaperLedger,PaperOrderV1
from shared_core.order_quantity import floor_quantity
from pathlib import Path

MAX_EXECUTION_QUOTE_AGE_SECONDS=5

@dataclass(frozen=True)
class ExecutionObservationV51:
    trade_date:str;side:str;strategy_id:str;decision_id:str;decision_snapshot_id:str;decision_time:str
    execution_snapshot_id:str;execution_observation_time:str;execution_time:str;code:str;bid1:float;bid1_volume:int;ask1:float;ask1_volume:int
    system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-execution-observation-v1"
    def __post_init__(self):
        strict_str(self.trade_date,"trade_date");strict_enum(self.side,"side",{"BUY","SELL"})
        for field in ("strategy_id","decision_id","decision_snapshot_id","execution_snapshot_id","code"):strict_str(getattr(self,field),field)
        if len(self.code)!=6 or not self.code.isdigit():raise ContractViolation("execution observation identity invalid")
        for field in ("bid1_volume","ask1_volume"):strict_int(getattr(self,field),field,0)
        for field in ("bid1","ask1"):strict_number(getattr(self,field),field)
        for field in ("decision_time","execution_observation_time","execution_time"):aware(getattr(self,field),field)
    @property
    def observation_id(self):return content_id("v51execobs1",asdict(self))
    def to_dict(self):return {**asdict(self),"observation_id":self.observation_id}

def build_execution_observation(snapshot:MarketSnapshotV1,*,side,strategy_id,decision_id,decision_snapshot_id,decision_time,execution_time,code):
    strict_enum(side,"side",{"BUY","SELL"})
    for field,value in (("strategy_id",strategy_id),("decision_id",decision_id),("decision_snapshot_id",decision_snapshot_id),("code",code)):strict_str(value,field)
    decision=aware(decision_time,"decision_time");observed=aware(snapshot.batch_completed_at,"execution_observation_time");executed=aware(execution_time,"execution_time")
    if not snapshot.quality.accepted or snapshot.snapshot_id==decision_snapshot_id:raise ContractViolation("independent accepted execution snapshot required")
    if not decision<observed<=executed:raise ContractViolation("decision_time < execution_observation_time <= execution_time required")
    if (executed-observed).total_seconds()>MAX_EXECUTION_QUOTE_AGE_SECONDS:raise ContractViolation("execution quote stale at fill time")
    if snapshot.trade_date!=executed.date().isoformat():raise ContractViolation("execution snapshot trade date invalid")
    expected_session="buy_execution" if side=="BUY" else "sell_execution"
    if snapshot.session!=expected_session:raise ContractViolation("wrong execution snapshot session")
    quote=next((x for x in snapshot.quotes if x.code==code),None)
    if quote is None or aware(quote.provider_time,"provider_time")>observed:raise ContractViolation("causal execution quote required")
    if side=="BUY" and (quote.ask1<=0 or quote.ask1_volume<=0 or quote.halted or quote.limit_up):raise ContractViolation("executable buy ask required")
    if side=="SELL" and (quote.bid1<=0 or quote.bid1_volume<=0 or quote.halted or quote.limit_down):raise ContractViolation("executable sell bid required")
    return ExecutionObservationV51(snapshot.trade_date,side,strategy_id,decision_id,decision_snapshot_id,decision.isoformat(),snapshot.snapshot_id,observed.isoformat(),executed.isoformat(),code,quote.bid1,quote.bid1_volume,quote.ask1,quote.ask1_volume)

class StrategyPaperExecutorV51:
    """One strategy, one ledger root; broker connectivity is intentionally absent."""
    def __init__(self,root,strategy_id):
        self.strategy_id=str(strategy_id);self.ledger=PaperLedger(Path(root)/self.strategy_id/"paper");self.engine=PaperEngine(self.ledger)
    def _validate(self,observation,side):
        if not isinstance(observation,ExecutionObservationV51) or observation.side!=side or observation.strategy_id!=self.strategy_id:raise ContractViolation("strategy execution observation mismatch")
        decision=aware(observation.decision_time,"decision_time");observed=aware(observation.execution_observation_time,"execution_observation_time");executed=aware(observation.execution_time,"execution_time")
        if observation.decision_snapshot_id==observation.execution_snapshot_id or not decision<observed<=executed or (executed-observed).total_seconds()>MAX_EXECUTION_QUOTE_AGE_SECONDS:raise ContractViolation("execution observation causal freshness invalid")
        return executed
    def buy(self,observation:ExecutionObservationV51,*,eligible_sell_date):
        at=self._validate(observation,"BUY");order=self.engine.buy_order(decision_id=observation.decision_id,code=observation.code,trade_date=observation.trade_date,at=at,ask1=observation.ask1,snapshot_id=observation.execution_snapshot_id,eligible_sell_date=eligible_sell_date)
        depth=floor_quantity(observation.code,observation.ask1_volume)
        if depth<=0:raise ContractViolation("execution ask depth below board lot")
        if order.shares>depth:order=PaperOrderV1(order.decision_id,order.side,order.code,order.trade_date,order.created_at,order.reference_price,depth,order.snapshot_id,order.eligible_sell_date)
        return self.engine.execute(order,at=at)
    def sell(self,observation:ExecutionObservationV51):
        at=self._validate(observation,"SELL");position=next((x for x in self.ledger.state()["positions"] if x["code"]==observation.code),None)
        if not position:raise ContractViolation("strategy position required")
        if observation.bid1_volume<int(position["shares"]):raise ContractViolation("execution bid depth insufficient")
        order=PaperOrderV1(position["decision_id"],"SELL",position["code"],observation.trade_date,at.isoformat(),str(observation.bid1),int(position["shares"]),observation.execution_snapshot_id,position["eligible_sell_date"])
        return self.engine.execute(order,at=at)
