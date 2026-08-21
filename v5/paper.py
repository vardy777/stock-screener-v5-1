"""V5-only event-sourced paper account; never sends broker orders."""
from __future__ import annotations
from dataclasses import dataclass,asdict
from datetime import datetime
from decimal import Decimal,ROUND_DOWN
import hashlib,json,os
from pathlib import Path
import msvcrt,time
from .core import ContractViolation
from .core import CHINA_TZ

D=lambda x:Decimal(str(x));CENT=Decimal("0.01")
def _id(prefix,value):return prefix+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:24]
def _replace_with_retry(source,target,timeout=3.0):
    deadline=time.monotonic()+timeout
    while True:
        try:os.replace(source,target);return
        except PermissionError:
            if time.monotonic()>=deadline:raise
            time.sleep(.01)
@dataclass(frozen=True)
class PaperOrderV1:
    decision_id:str;side:str;code:str;trade_date:str;created_at:str;reference_price:str;shares:int;snapshot_id:str;eligible_sell_date:str;schema_version:str="v5-paper-order-v1"
    @property
    def order_id(self):return _id("ord1-",asdict(self))
@dataclass(frozen=True)
class PaperEventV1:
    order_id:str;outcome:str;reason:str;recorded_at:str;code:str;side:str;shares:int;fill_price:str;commission:str;tax:str;cash_flow:str;decision_id:str;trade_date:str;eligible_sell_date:str;schema_version:str="v5-paper-event-v1"
    @property
    def event_id(self):return _id("evt1-",asdict(self))

class PaperLedger:
    def __init__(self,root,initial_cash=100000):self.root=Path(root);self.path=self.root/"events.json";self.initial=D(initial_cash)
    def events(self):
        if not self.path.exists():return []
        data=json.loads(self.path.read_text(encoding="utf-8"));rows=data.get("events",[])
        previous="genesis"
        for index,row in enumerate(rows,1):
            if row.get("sequence")!=index or row.get("previous_event_id")!=previous:raise ContractViolation("paper event chain invalid")
            event=PaperEventV1(**row["event"])
            if row.get("event_id")!=event.event_id:raise ContractViolation("paper event hash invalid")
            previous=event.event_id
        if data.get("head")!=previous:raise ContractViolation("paper ledger head invalid")
        return rows
    def save_order(self,order):
        path=self.root/"orders"/order.trade_date/f"{order.order_id}.json";path.parent.mkdir(parents=True,exist_ok=True);raw=json.dumps(asdict(order)|{"order_id":order.order_id},ensure_ascii=False,sort_keys=True,separators=(",",":"))
        if path.exists():
            if path.read_text(encoding="utf-8")!=raw:raise ContractViolation("paper order immutable collision")
            return path
        tmp=path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
        try:os.link(tmp,path)
        except FileExistsError:
            if path.read_text(encoding="utf-8")!=raw:raise ContractViolation("paper order immutable collision")
        finally:tmp.unlink(missing_ok=True)
        return path
    def pending_orders(self):
        completed={row["event"]["order_id"] for row in self.events()};pending=[]
        for path in (self.root/"orders").glob("*/*.json") if (self.root/"orders").exists() else []:
            row=json.loads(path.read_text(encoding="utf-8"));order_id=row.pop("order_id")
            order=PaperOrderV1(**row)
            if order.order_id!=order_id:raise ContractViolation("paper order hash invalid")
            if order_id not in completed:pending.append(order)
        return sorted(pending,key=lambda order:(order.created_at,order.order_id))
    def recovery_report(self):
        pending=self.pending_orders();return {"schema_version":"v5-paper-recovery-v1","status":"RECOVERY_REQUIRED" if pending else "CLEAN","pending_orders":[{"order_id":order.order_id,"side":order.side,"code":order.code,"trade_date":order.trade_date,"snapshot_id":order.snapshot_id} for order in pending]}
    def append(self,event):
        self.root.mkdir(parents=True,exist_ok=True);lock_path=self.root/"events.lock"
        with lock_path.open("a+b") as lock:
            deadline=time.monotonic()+10
            while True:
                try:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);break
                except OSError:
                    if time.monotonic()>=deadline:raise ContractViolation("paper ledger lock timeout")
                    time.sleep(.02)
            try:
                rows=self.events()
                if any(x["event"]["order_id"]==event.order_id for x in rows):return False
                previous=rows[-1]["event_id"] if rows else "genesis";rows.append({"sequence":len(rows)+1,"previous_event_id":previous,"event_id":event.event_id,"event":asdict(event)})
                payload={"schema_version":"v5-paper-ledger-v1","initial_cash":str(self.initial),"head":event.event_id,"events":rows};tmp=self.path.with_suffix(f".{os.getpid()}.{event.event_id}.tmp");tmp.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")),encoding="utf-8");_replace_with_retry(tmp,self.path);return True
            finally:
                lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
    def state(self,*,as_of=None):
        cash=self.initial;positions={};rejected=[]
        for row in self.events():
            e=row["event"]
            if as_of is not None and datetime.fromisoformat(e["recorded_at"])>as_of:continue
            if e["outcome"]!="FILLED":rejected.append(e);continue
            cash+=D(e["cash_flow"])
            if e["side"]=="BUY":positions[e["code"]]=e
            else:positions.pop(e["code"],None)
        return {"initial_cash":float(self.initial),"cash":float(cash.quantize(CENT)),"positions":list(positions.values()),"rejections":rejected,"event_count":len(self.events())}
    def reconcile(self):
        state=self.state();cash=self.initial+sum((D(x["event"]["cash_flow"]) for x in self.events() if x["event"]["outcome"]=="FILLED"),D(0))
        return {"passed":D(str(state["cash"]))==cash.quantize(CENT),"cash":state["cash"],"event_count":state["event_count"]}
    def round_trips(self,*,as_of=None):
        all_events=self.events();event_ids={row["event"]["order_id"]:row["event_id"] for row in all_events};open_buys={};trips=[]
        for row in all_events:
            event=row["event"]
            if as_of is not None and datetime.fromisoformat(event["recorded_at"])>as_of:continue
            if event["outcome"]!="FILLED":continue
            key=(event["decision_id"],event["code"])
            if event["side"]=="BUY":open_buys[key]=event;continue
            buy=open_buys.pop(key,None)
            if buy is None:raise ContractViolation("paper sell has no matching buy")
            invested=-D(buy["cash_flow"]);proceeds=D(event["cash_flow"]);pnl=(proceeds-invested).quantize(CENT)
            trips.append({"schema_version":"v5-paper-round-trip-v1","decision_id":event["decision_id"],"code":event["code"],"buy_trade_date":buy["trade_date"],"sell_trade_date":event["trade_date"],"buy_event_id":event_ids[buy["order_id"]],"sell_event_id":row["event_id"],"shares":event["shares"],"invested":float(invested),"proceeds":float(proceeds),"net_pnl":float(pnl),"net_return":float(pnl/invested) if invested else 0.0})
        return trips

class PaperEngine:
    def __init__(self,ledger,commission_rate="0.0003",minimum_commission="5",stamp_tax="0.0005",slippage="0.0005"):
        self.ledger=ledger;self.commission_rate=D(commission_rate);self.minimum_commission=D(minimum_commission);self.stamp_tax=D(stamp_tax);self.slippage=D(slippage)
    def _reject(self,order,reason,at):return PaperEventV1(order.order_id,"REJECTED",reason,at.isoformat(),order.code,order.side,order.shares,"0","0","0","0",order.decision_id,order.trade_date,order.eligible_sell_date)
    def reject(self,order,reason,*,at):
        self.ledger.save_order(order)
        event=self._reject(order,reason,at.astimezone(CHINA_TZ));self.ledger.append(event);return event
    def execute(self,order,*,at):
        if at.tzinfo is None or at.utcoffset() is None:raise ContractViolation("paper execution timezone required")
        current=at.astimezone(CHINA_TZ);created=datetime.fromisoformat(order.created_at)
        if created.tzinfo is None or created.utcoffset() is None:raise ContractViolation("paper order timezone required")
        if created.astimezone(CHINA_TZ)>current:raise ContractViolation("paper order created in future")
        if order.trade_date!=current.date().isoformat():raise ContractViolation("paper execution trade date mismatch")
        clock=(current.hour,current.minute,current.second)
        if order.side=="BUY" and not ((14,50,0)<=clock<=(14,51,59)):raise ContractViolation("paper buy outside strict window")
        if order.side=="SELL" and not ((9,30,0)<=clock<=(11,30,0) or (13,0,0)<=clock<=(15,0,0)):raise ContractViolation("paper sell outside continuous auction")
        self.ledger.save_order(order)
        for row in self.ledger.events():
            if row["event"]["order_id"]==order.order_id:return PaperEventV1(**row["event"])
        state=self.ledger.state();positions={x["code"]:x for x in state["positions"]};price=D(order.reference_price)*(D(1)+self.slippage if order.side=="BUY" else D(1)-self.slippage);notional=(price*order.shares).quantize(CENT);commission=max(self.minimum_commission,(notional*self.commission_rate).quantize(CENT));tax=(notional*self.stamp_tax).quantize(CENT) if order.side=="SELL" else D(0)
        reason=""
        if order.shares<=0 or order.shares%100:reason="INVALID_BOARD_LOT"
        elif order.side=="BUY" and (order.code in positions):reason="DUPLICATE_POSITION"
        elif order.side=="BUY" and notional+commission>self.ledger.initial/D(3):reason="ONE_THIRD_CAP"
        elif order.side=="BUY" and notional+commission>D(str(state["cash"])):reason="INSUFFICIENT_CASH"
        elif order.side=="SELL" and order.code not in positions:reason="POSITION_MISSING"
        elif order.side=="SELL" and order.trade_date<positions[order.code]["eligible_sell_date"]:reason="T_PLUS_ONE"
        event=self._reject(order,reason,current) if reason else PaperEventV1(order.order_id,"FILLED","FILLED",current.isoformat(),order.code,order.side,order.shares,str(price.quantize(CENT)),str(commission),str(tax),str((-notional-commission if order.side=="BUY" else notional-commission-tax).quantize(CENT)),order.decision_id,order.trade_date,order.eligible_sell_date)
        self.ledger.append(event);return event
    def buy_order(self,*,decision_id,code,trade_date,at,ask1,snapshot_id,eligible_sell_date):
        budget=min(self.ledger.initial/D(3),D(str(self.ledger.state()["cash"])));price=D(ask1)*(D(1)+self.slippage);shares=int(((budget-self.minimum_commission)/price/100).to_integral_value(rounding=ROUND_DOWN))*100
        return PaperOrderV1(decision_id,"BUY",code,trade_date,at.isoformat(),str(ask1),shares,snapshot_id,eligible_sell_date)
