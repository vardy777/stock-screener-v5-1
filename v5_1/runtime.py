"""Single V5.1 research runtime with strict wall-clock and storage isolation."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime,time,timedelta
import json,os,msvcrt,socket,secrets
from pathlib import Path
from shared_core.calendar import TradingCalendar
from shared_core.core import CHINA_TZ,ContractViolation,strict_bool,strict_number,strict_int
from shared_core.market_state import MarketStateV1
from shared_core.market_snapshot import MarketSnapshotV1,QuoteV1
from . import BASELINE_STRATEGY_VERSION,CLOSESCAN_STRATEGY_VERSION
from .decision import build_morning_pool,build_confirmation,DecisionSnapshotRepository
from .closescan import build_facts
from .execution import build_execution_observation,StrategyPaperExecutorV51
from .facts import save_immutable,content_id
from .production_read_model import ProductionRunFactV51,ProductionFailureFactV51,ExecutionResultFactV51,ExecutionRejectionFactV51,ExitDecisionFactV51,HealthFactV51,AcceptanceFactV51,RoundTripAcceptanceFactV51,StageOutcomeFactV51,ImmutableReadModelBuilder
from .providers import V51MarketDataProvider
from .master_sources import CrossVerifiedMasterDirectory
from .security_master import SecurityMasterRepository,SecurityMasterVersionV1,MasterVerificationV1,aware
from .master_evidence import DirectoryResponseFactV51,MasterMatchFactV51,MasterEvidenceRepository
from .tradability import DailySecurityStatusRepository,DailySecurityStatusV1,derive_tradability
from .storage import V51FactStore
from .decision import MorningPoolV51,FeatureFreezeV51,BaselineConfirmationV51
from .closescan import CloseScanSelectionV1

MODES={"SHADOW","PRODUCTION_RESEARCH","REPLAY","TEST"}
MODE_META={"SHADOW":("V51_SHADOW",False),"PRODUCTION_RESEARCH":("V51_PRODUCTION_STRICT",True),"REPLAY":("V51_REPLAY",False),"TEST":("V51_TEST",False)}
WINDOWS={"preflight":(time(8,0),time(9,29,59)),"morning_observation":(time(9,30),time(9,34,59)),"morning_pool":(time(9,35),time(9,35,59)),"morning_notification":(time(9,35),time(9,39,59)),"feature_freeze":(time(14,49),time(14,49,59)),"confirmation":(time(14,50),time(14,51,59)),"confirmation_notification":(time(14,50),time(14,52,59)),"execution":(time(14,50,1),time(14,51,59)),"next_open_exit":(time(9,30),time(9,30,59)),"round_trip_acceptance":(time(9,30),time(23,59,59)),"health":(time(14,53),time(15,19,59)),"acceptance":(time(15,20),time(23,59,59))}

def _json(path):return json.loads(Path(path).read_text(encoding="utf-8"))
def _one(folder,label):
    paths=sorted(Path(folder).glob("*.json")) if Path(folder).exists() else []
    if len(paths)!=1:raise ContractViolation(f"{label} missing or ambiguous")
    row=_json(paths[0]);matches=[(field,prefix,row.get(field)) for field,prefix in ENTITY_PREFIXES.items() if row.get(field)==paths[0].stem]
    if len(matches)!=1:raise ContractViolation(f"{label} identity missing or ambiguous")
    field,prefix,claimed=matches[0];unsigned=dict(row);unsigned.pop(field)
    if content_id(prefix,unsigned)!=claimed or paths[0].stem!=claimed:raise ContractViolation(f"{label} content-address mismatch")
    if row.get("system_version")!="5.1" or row.get("contract_version")!="v5.1-contract-v1":raise ContractViolation(f"{label} version mismatch")
    return row

ENTITY_PREFIXES={"verification_id":"smverify1","tradability_id":"tradability1","pool_id":"v51mp1","freeze_id":"v51freeze1","confirmation_id":"v51confirm1","candidate_fact_id":"v51cscandidates1","selection_id":"closescan1","execution_result_id":"v51execresult1","rejection_id":"v51execreject1","exit_decision_id":"v51exitdecision1","health_id":"v51health1","acceptance_id":"v51accept1","round_trip_acceptance_id":"v51roundaccept1","stage_outcome_id":"v51stageoutcome1","receipt_id":"v51notify1"}

class V51Runtime:
    def __init__(self,root=None,*,mode="SHADOW",clock=None,provider=None,master_provider=None,calendar=None):
        if mode not in MODES:raise ContractViolation("V5.1 runtime mode invalid")
        base=Path(__file__).resolve().parent;production=(base/"data").resolve();shadow=(base/"shadow_data").resolve();defaults={"PRODUCTION_RESEARCH":production,"SHADOW":shadow,"REPLAY":base/"replay","TEST":base/"test_data"};chosen=Path(root).resolve() if root is not None else Path(defaults[mode]).resolve()
        injected=any(x is not None for x in (clock,provider,master_provider,calendar))
        if mode=="PRODUCTION_RESEARCH" and injected:raise ContractViolation("production runtime forbids injected clock/providers/calendar")
        if mode=="PRODUCTION_RESEARCH" and chosen!=production:raise ContractViolation("production runtime physical root fixed")
        if mode=="SHADOW" and not injected and chosen!=shadow:raise ContractViolation("shadow runtime physical root fixed")
        if mode in {"REPLAY","TEST"} and (chosen in {production,shadow} or production in chosen.parents or shadow in chosen.parents):raise ContractViolation("replay/test cannot target production or shadow fact root")
        self.mode=mode;self.cohort,self.strict_evidence=MODE_META[mode];self.root=chosen;self.clock=clock or (lambda:datetime.now(CHINA_TZ));self.provider=provider or V51MarketDataProvider();self.master_provider=master_provider or CrossVerifiedMasterDirectory();self.calendar=calendar or TradingCalendar();self.store=V51FactStore(self.root);self.master=SecurityMasterRepository(self.root);self.master_evidence=MasterEvidenceRepository(self.root);self.statuses=DailySecurityStatusRepository(self.root);self.decisions=DecisionSnapshotRepository(self.root)
    def now(self):
        value=self.clock()
        if value.tzinfo is None:raise ContractViolation("runtime clock must be aware")
        return value.astimezone(CHINA_TZ)
    @contextmanager
    def _lock(self,day,stage):
        path=self.root/"locks"/f"{day}-{stage}.lock";path.parent.mkdir(parents=True,exist_ok=True);handle=path.open("a+b");token=secrets.token_hex(16)
        try:
            handle.seek(0)
            try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as exc:raise ContractViolation("V5.1 stage single-writer lock held") from exc
            metadata={"pid":os.getpid(),"host":socket.gethostname(),"owner_token":token,"acquired_at":self.now().isoformat()};handle.seek(0);handle.truncate();handle.write(json.dumps(metadata,sort_keys=True).encode());handle.flush()
            yield
            handle.seek(0);stored=json.loads(handle.read().decode() or "{}")
            if stored.get("owner_token")!=token:raise ContractViolation("V5.1 stage lock ownership changed")
        finally:
            try:handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            except OSError:pass
            handle.close()
    def _window(self,stage,now):
        if self.mode in {"REPLAY","TEST"}:return
        start,end=WINDOWS[stage];clock=now.timetz().replace(tzinfo=None)
        if not start<=clock<=end:raise ContractViolation(f"V5.1 {stage} outside actual window")
    def _record(self,day,stage,now,outcome,entity_id=""):
        fact=ProductionRunFactV51(day,stage,now.isoformat(),outcome,entity_id,self.mode,self.cohort,self.strict_evidence);self.store.save("production_runs",fact);return fact
    def _failure(self,day,stage,now,exc):
        fact=ProductionFailureFactV51(day,stage,now.isoformat(),f"{type(exc).__name__}:{exc}",self.mode,self.cohort,self.strict_evidence);self.store.save("production_failures",fact);return fact
    def _validated_runs(self,day):
        rows=[]
        for path in sorted((self.root/"production_runs"/day).glob("*.json")) if (self.root/"production_runs"/day).exists() else ():
            row=_json(path);claimed=row.pop("run_id","");fact=ProductionRunFactV51(**row)
            if claimed!=fact.run_id or path.stem!=claimed:raise ContractViolation("production run content-address mismatch")
            if fact.runtime_mode!=self.mode or fact.cohort!=self.cohort or fact.strict_evidence!=self.strict_evidence:raise ContractViolation("production run mode/cohort mismatch")
            value=fact.to_dict();rows.append(value)
        return rows
    def _validate_entity(self,day,entity_id):
        matches=list(self.root.rglob(f"{entity_id}.json"))
        if len(matches)!=1:raise ContractViolation("run entity missing or ambiguous")
        row=_json(matches[0]);id_fields=[name for name in ENTITY_PREFIXES if row.get(name)==entity_id]
        if len(id_fields)!=1:raise ContractViolation("run entity declared id mismatch")
        field=id_fields[0];unsigned=dict(row);unsigned.pop(field);expected=content_id(ENTITY_PREFIXES[field],unsigned)
        if expected!=entity_id or matches[0].stem!=entity_id:raise ContractViolation("run entity content-address mismatch")
        return row
    def run(self,stage):
        if stage not in WINDOWS:raise ContractViolation("unsupported V5.1 task")
        now=self.now();day=now.date().isoformat()
        if not self.calendar.is_open(now.date()):raise ContractViolation("V5.1 task rejected non-trading day")
        with self._lock(day,stage):
            prior=self._validated_runs(day)
            for row in sorted(prior,key=lambda x:(x["completed_at"],x["run_id"]),reverse=True):
                if row.get("task_name")==stage and row.get("outcome")=="SUCCESS":self._validate_entity(day,row["entity_id"]);return {"passed":True,"accepted":True,"idempotent":True,"entity":row["entity_id"],"run":row}
            try:
                self._window(stage,now);details=getattr(self,f"_{stage}")(day,now);run=self._record(day,stage,now,"SUCCESS",str(details.get("entity_id","")))
                if stage=="acceptance":
                    from .production_read_model import ImmutableReadModelBuilder
                    details["projection_state"]=ImmutableReadModelBuilder(self.root).build_and_save(day).state
                return {"passed":True,"details":details,"run":run.to_dict()}
            except Exception as exc:
                failure=self._failure(day,stage,now,exc);run=self._record(day,stage,now,"FAILED",failure.failure_id);return {"passed":False,"error":str(exc),"failure":failure.to_dict(),"run":run.to_dict()}
    def _preflight(self,day,now):
        records,diag=self.master_provider.discover();versions=[]
        for record in records:
            if isinstance(record,str):code=record;name=record;listing_date=None
            else:code=str(record["code"]);name=str(record["name"]);listing_date=str(record["listing_date"])
            if self.mode not in {"REPLAY","TEST"} and (not listing_date or name==code):raise ContractViolation("production master requires real name and listing date")
            listing_date=listing_date or "1990-01-01"
            exchange=str(record.get("exchange")) if not isinstance(record,str) and record.get("exchange") else ("SSE" if code.startswith("6") else "SZSE");board="STAR" if code.startswith(("688","689")) else "CHINEXT" if code.startswith("30") else "MAIN"
            source_family=str(record.get("source_family")) if not isinstance(record,str) and record.get("source_family") else self.master_provider.provider_family
            source_record_id=str(record.get("source_record_id")) if not isinstance(record,str) and record.get("source_record_id") else f"{self.master_provider.source_id}:{code}"
            version=SecurityMasterVersionV1.build(symbol=code,exchange=exchange,board=board,security_name=name,listing_date=listing_date,valid_from=listing_date,known_at=now,source_family=source_family,source_record_id=source_record_id);self.master.append(version);versions.append(version)
        response_ids=[];response_by_family={};response_by_key={}
        for row in diag.get("responses",()):
            response=DirectoryResponseFactV51.build(**row);self.master_evidence.save_response(response);response_ids.append(response.response_id);response_by_family[(response.provider_family,response.exchange)]=response.response_id
            if row.get("response_key"):response_by_key[str(row["response_key"])]=response.response_id
        match_ids=[]
        for row in diag.get("matches",()):
            official_id=response_by_family.get((str(row["official_family"]),str(row["exchange"])))
            third_id=(response_by_key.get(str(row.get("third_party_response_key"))) or response_by_family.get((str(row.get("third_party_family")),"ALL"))) if row.get("third_party_family") else None
            match=MasterMatchFactV51.build(symbol=row["symbol"],exchange=row["exchange"],official_response_id=official_id,third_party_response_id=third_id,official_name=row["official_name"],official_listing_date=row["official_listing_date"],third_party_name=row.get("third_party_name"),third_party_listing_date=row.get("third_party_listing_date"),outcome=row["outcome"],matched_at=row["matched_at"]);self.master_evidence.save_match(match);match_ids.append(match.match_id)
        independent=tuple(diag.get("independent_source_families",()))
        if self.mode not in {"REPLAY","TEST"} and (not diag.get("official_independent_source") or not independent or self.master_provider.provider_family in independent):raise ContractViolation("PENDING_INDEPENDENT_SOURCE: Eastmoney-only Master cannot be VERIFIED")
        if self.mode in {"REPLAY","TEST"} and not independent:independent=(self.master_provider.provider_family,)
        families=tuple(diag.get("source_families") or [self.master_provider.provider_family,*independent])
        if self.mode not in {"REPLAY","TEST"} and (not response_ids or len(match_ids)!=len(versions)):raise ContractViolation("production master evidence chain incomplete")
        verification=MasterVerificationV1.build(verified_for_trade_date=day,verified_at=now,source_families=families,independent_source_families=independent,master_version_ids=[x.version_id for x in versions],record_count=len(versions),response_ids=response_ids,match_ids=match_ids);self.master.verify(verification)
        # Directory presence establishes identity only. Unknown same-day trading state remains fail closed until observation creates status.
        redacted={k:v for k,v in diag.items() if k not in {"responses","matches"}}
        redacted["evidence"]={"response_count":len(response_ids),"match_count":len(match_ids),"verification_id":verification.verification_id}
        return {"entity_id":verification.verification_id,"master_count":len(versions),"directory_diagnostics":redacted,"daily_tradability":"PENDING_0930_OBSERVATION"}
    def _morning_observation(self,day,now):
        verification=self.master.require_fresh(day,now,self.calendar);masters=self.master.as_of(day,now);result=self.provider.acquire([x.symbol for x in masters],trade_date=day,stage="morning_observation",now=now);snap=result.primary;statuses=[]
        self._persist_acquisition(day,"morning_observation",result);sources=tuple(getattr(result,"sources",()))
        if len(sources)!=2:raise ContractViolation("daily status requires two raw source snapshots")
        source_maps=[]
        for source in sources:
            payload={"snapshot_id":source.snapshot_id,"trade_date":source.trade_date,"session":source.session,"batch_started_at":source.batch_started_at,"batch_completed_at":source.batch_completed_at,"quality":asdict(source.quality),"quotes":[q.to_dict() for q in source.quotes],"schema_version":source.schema_version};save_immutable(self.root/"source_snapshots"/day/f"{source.snapshot_id}.json",payload);source_maps.append((source,{q.code:q for q in source.quotes}))
        consensus_id=content_id("v51consensus",result.report);save_immutable(self.root/"consensus_reports"/day/f"{consensus_id}.json",{**result.report,"consensus_id":consensus_id,"trade_date":day})
        for master in masters:
            evidence=[(source,mapping.get(master.symbol)) for source,mapping in source_maps];present=[(source,q) for source,q in evidence if q is not None];states=[("ST" in q.name.upper(),q.halted,"退" in q.name) for _,q in present];known=len(present)==2 and len(set(states))==1;conflict=len(present)!=2 or len(set(states))!=1
            sessions=sum(1 for value,is_open in self.calendar.sessions.items() if is_open and master.listing_date<=value<=day);new_listing=sessions<=5
            families=[q.provider for _,q in present];snapshot_ids=[source.snapshot_id for source,q in present]
            state=states[0] if known else (False,False,False)
            status=DailySecurityStatusV1.build(trade_date=day,symbol=master.symbol,observed_at=now,known_at=now,is_st=state[0],suspended=state[1],delisting_period=state[2],new_listing=new_listing,status_known=known,conflict=conflict,source_families=families or ["NO_SOURCE_EVIDENCE"],source_snapshot_ids=snapshot_ids);self.statuses.save(status);statuses.append(status)
        tradability=derive_tradability(masters,statuses,trade_date=day,decided_at=now,master_verification=verification,master_repository=self.master,status_repository=self.statuses,calendar=self.calendar);self.store.save("tradability",tradability);save_immutable(self.root/"market_observations"/day/f"{snap.snapshot_id}.json",{"snapshot_id":snap.snapshot_id,"trade_date":day,"session":snap.session,"batch_started_at":snap.batch_started_at,"batch_completed_at":snap.batch_completed_at,"quality":asdict(snap.quality),"quotes":[q.to_dict() for q in snap.quotes]});return {"entity_id":tradability.tradability_id,"snapshot_id":snap.snapshot_id,"coverage":snap.quality.coverage}
    def _load_tradability(self,day):
        row=_one(self.root/"tradability"/day,"tradability");
        from .tradability import DailyTradabilityFactV1
        if row["trade_date"]!=day:raise ContractViolation("tradability trade date mismatch")
        fact=DailyTradabilityFactV1(row["trade_date"],row["decided_at"],row["master_verification_id"],tuple(row["master_version_ids"]),tuple(row["status_ids"]),tuple(row["eligible_symbols"]),tuple(row["rejections"]),strict_number(row["coverage"],"coverage"),strict_bool(row["accepted"],"accepted"));
        if fact.tradability_id!=row["tradability_id"]:raise ContractViolation("tradability identity mismatch")
        return fact
    def _acquire(self,day,now,stage,codes=None):
        trad,result=self._acquire_result(day,now,stage,codes);return trad,result.primary,result.report
    def _acquire_result(self,day,now,stage,codes=None):
        trad=self._load_tradability(day);result=self.provider.acquire(codes or trad.eligible_symbols,trade_date=day,stage=stage,now=now);self._persist_acquisition(day,stage,result);return trad,result
    def _persist_acquisition(self,day,stage,result):
        for source in tuple(getattr(result,"sources",())):
            payload={"snapshot_id":source.snapshot_id,"trade_date":source.trade_date,"session":source.session,"batch_started_at":source.batch_started_at,"batch_completed_at":source.batch_completed_at,"quality":asdict(source.quality),"quotes":[q.to_dict() for q in source.quotes],"schema_version":source.schema_version};save_immutable(self.root/"source_snapshots"/day/f"{source.snapshot_id}.json",payload)
        snapshot=result.primary;payload={"snapshot_id":snapshot.snapshot_id,"trade_date":snapshot.trade_date,"session":snapshot.session,"batch_started_at":snapshot.batch_started_at,"batch_completed_at":snapshot.batch_completed_at,"quality":asdict(snapshot.quality),"quotes":[q.to_dict() for q in snapshot.quotes],"schema_version":snapshot.schema_version};save_immutable(self.root/"snapshots"/day/f"{snapshot.snapshot_id}.json",payload)
        report={**result.report,"trade_date":day,"stage":stage};identity=content_id("v51consensus",report);save_immutable(self.root/"consensus_reports"/day/f"{identity}.json",{**report,"consensus_id":identity})
        state=MarketStateV1.from_snapshot(snapshot);save_immutable(self.root/"market_states"/day/f"{state.market_state_id}.json",state.to_dict())
    def _snapshot(self,path):
        row=_json(path);snapshot=MarketSnapshotV1.build(trade_date=row["trade_date"],session=row["session"],batch_started_at=row["batch_started_at"],batch_completed_at=row["batch_completed_at"],quotes=[QuoteV1.from_mapping(q) for q in row["quotes"]],expected_codes=row["quality"]["expected_codes"])
        if snapshot.snapshot_id!=row.get("snapshot_id") or Path(path).stem!=snapshot.snapshot_id:raise ContractViolation("snapshot content-address mismatch")
        return snapshot
    def _pool(self,day):
        row=_one(self.root/"morning_pools"/day,"morning pool");return MorningPoolV51(row["trade_date"],row["decided_at"],row["tradability_id"],row["snapshot_id"],row["market_state_id"],row["funnel_id"],tuple(row["candidates"]),row["strategy_version"],row["system_version"],row["contract_version"],row["schema_version"])
    def _morning_pool(self,day,now):
        trad,snap,report=self._acquire(day,now,"morning_0935");state=MarketStateV1.from_snapshot(snap);pool=build_morning_pool(snap,trad,decided_at=now,market_state_id=state.market_state_id,market_valid=state.trade_allowed);self.store.save("morning_pools",pool);return {"entity_id":pool.pool_id,"snapshot_id":snap.snapshot_id,"coverage":snap.quality.coverage,"candidate_count":len(pool.candidates),"consensus":report.get("consistent_ratio")}
    def _feature_freeze(self,day,now):
        trad,snap,report=self._acquire(day,now,"signal");freeze=self.decisions.freeze(snap,now);return {"entity_id":freeze.freeze_id,"snapshot_id":snap.snapshot_id,"coverage":snap.quality.coverage,"consensus":report.get("consistent_ratio")}
    def _confirmation(self,day,now):
        pool=self._pool(day);freeze_row=_one(self.root/"feature_freezes"/day,"feature freeze");freeze=FeatureFreezeV51(freeze_row["trade_date"],freeze_row["frozen_at"],freeze_row["decision_snapshot_id"],freeze_row["system_version"],freeze_row["contract_version"],freeze_row["schema_version"]);snapshot=self._snapshot(self.root/"decision_snapshots"/day/f"{freeze.decision_snapshot_id}.json");state=MarketStateV1.from_snapshot(snapshot);trad=self._load_tradability(day)
        baseline=build_confirmation(pool,snapshot,freeze=freeze,snapshot_repository=self.decisions,decided_at=now,market_state_id=state.market_state_id,market_valid=state.trade_allowed);self.store.save("confirmations",baseline)
        close=build_facts(snapshot,trad,freeze=freeze,snapshot_repository=self.decisions,decided_at=now,market_state_id=state.market_state_id,market_valid=state.trade_allowed);self.store.save("closescan_candidates",close.candidates);self.store.save("closescan_selections",close.selection);self.store.save("closescan_runs",close.run)
        return {"entity_id":baseline.confirmation_id,"baseline_confirmation_id":baseline.confirmation_id,"baseline_outcome":baseline.outcome,"closescan_selection_id":close.selection.selection_id,"closescan_outcome":close.selection.outcome}
    def _execution(self,day,now):
        baseline=_one(self.root/"confirmations"/day,"baseline confirmation");close=_one(self.root/"closescan_selections"/day,"CloseScan selection");selected=[]
        for strategy,row,id_field in ((BASELINE_STRATEGY_VERSION,baseline,"confirmation_id"),(CLOSESCAN_STRATEGY_VERSION,close,"selection_id")):
            if row.get("candidates"):selected.append((strategy,row,row["candidates"][0],row[id_field]))
        if not selected:
            fact=StageOutcomeFactV51(day,"execution","ACTIVE_FLAT",(BASELINE_STRATEGY_VERSION,CLOSESCAN_STRATEGY_VERSION),now.isoformat(),self.mode,self.cohort,self.strict_evidence);self.store.save("stage_outcomes",fact);return {"entity_id":fact.stage_outcome_id,"outcome":"ACTIVE_FLAT","intent_count":0}
        events=[];eligible=self.calendar.next_open(now.date()).isoformat();books={}
        for code in sorted({x[2]["code"] for x in selected}):
            try:
                _,acquired=self._acquire_result(day,now,"buy_execution",[code]);books[code]=(acquired.primary,acquired.report,self.now(),tuple(x.snapshot_id for x in getattr(acquired,"sources",())))
            except Exception as exc:books[code]=exc
        for strategy,row,candidate,decision_id in selected:
            code=candidate["code"]
            try:
                if isinstance(books[code],Exception):raise books[code]
                snapshot,report,executed,source_ids=books[code];obs=build_execution_observation(snapshot,side="BUY",strategy_id=strategy,decision_id=decision_id,decision_snapshot_id=row["decision_snapshot_id"],decision_time=row["decided_at"],execution_time=executed,code=code);self.store.save("execution_observations",obs);event=StrategyPaperExecutorV51(self.root,strategy).buy(obs,eligible_sell_date=eligible);result=ExecutionResultFactV51(day,strategy,"BUY",obs.observation_id,event.event_id,event.outcome,executed.isoformat(),self.mode,self.cohort,self.strict_evidence);self.store.save("execution_results",result);events.append(result.to_dict())
            except Exception as exc:
                completed=self.now();source_ids=books[code][3] if not isinstance(books[code],Exception) else ();rejected=ExecutionRejectionFactV51(day,strategy,"BUY",code,decision_id,source_ids,f"{type(exc).__name__}:{exc}",completed.isoformat(),self.mode,self.cohort,self.strict_evidence);self.store.save("execution_rejections",rejected);events.append(rejected.to_dict())
        filled=sum(x.get("outcome")=="FILLED" for x in events);rejected=len(events)-filled;reasons=" ".join(x.get("reason_code","") for x in events)
        outcome="ALL_FILLED" if filled==len(events) else "PARTIAL_FILL" if filled else "FAIL_CLOSED" if any(x in reasons for x in ("OSError","RuntimeError","TimeoutError")) else "NO_STRICT_FILL" if any(x in reasons for x in ("ask","depth","halt","limit")) else "EXECUTION_REJECTED"
        intents=tuple(f"{strategy}:{decision}:{candidate['code']}" for strategy,_,candidate,decision in selected);audit=tuple(x.get("execution_result_id") or x["rejection_id"] for x in events);fact=StageOutcomeFactV51(day,"execution",outcome,tuple(sorted({x[0] for x in selected})),self.now().isoformat(),self.mode,self.cohort,self.strict_evidence,len(selected),filled,rejected,intents,audit);self.store.save("stage_outcomes",fact)
        return {"entity_id":fact.stage_outcome_id,"outcome":outcome,"intent_count":len(selected),"result_count":filled,"rejection_count":rejected,"execution_snapshot_ids":sorted({value[0].snapshot_id for value in books.values() if not isinstance(value,Exception)}),"results":events}
    def _next_open_exit(self,day,now):
        executors=[StrategyPaperExecutorV51(self.root,x) for x in (BASELINE_STRATEGY_VERSION,CLOSESCAN_STRATEGY_VERSION)];positions=[]
        for executor in executors:
            for position in executor.ledger.state()["positions"]:
                if position["eligible_sell_date"]<=day:positions.append((executor,position))
        if not positions:
            fact=StageOutcomeFactV51(day,"next_open_exit","NO_POSITIONS",(BASELINE_STRATEGY_VERSION,CLOSESCAN_STRATEGY_VERSION),now.isoformat(),self.mode,self.cohort,self.strict_evidence);self.store.save("stage_outcomes",fact);return {"entity_id":fact.stage_outcome_id,"outcome":"ACTIVE_FLAT"}
        executed=self.now();results=[];books={}
        for code in sorted({p[1]["code"] for p in positions}):
            try:
                acquired=self.provider.acquire([code],trade_date=day,stage="sell_execution",now=now);self._persist_acquisition(day,"sell_execution",acquired);books[code]=(acquired.primary,acquired.report,acquired)
            except Exception as exc:books[code]=exc
        for executor,position in positions:
            code=position["code"]
            try:
                if isinstance(books[code],Exception):raise books[code]
                snapshot,report,_=books[code];prior=[]
                for path in (self.root/"execution_observations").glob("*/*.json"):
                    row=_json(path)
                    if row.get("strategy_id")==executor.strategy_id and row.get("side")=="BUY" and row.get("decision_id")==position["decision_id"]:prior.append(row)
                if len(prior)!=1:raise ContractViolation("sell lineage requires one prior buy execution observation")
                exit_decision=ExitDecisionFactV51(day,executor.strategy_id,code,position["decision_id"],prior[0]["observation_id"],position["eligible_sell_date"],now.isoformat(),self.mode,self.cohort,self.strict_evidence);self.store.save("exit_decisions",exit_decision)
                fill_time=aware(snapshot.batch_completed_at,"sell snapshot completed");obs=build_execution_observation(snapshot,side="SELL",strategy_id=executor.strategy_id,decision_id=exit_decision.exit_decision_id,decision_snapshot_id=prior[0]["execution_snapshot_id"],decision_time=exit_decision.decided_at,execution_time=fill_time,code=code);self.store.save("execution_observations",obs);event=executor.sell(obs);result=ExecutionResultFactV51(day,executor.strategy_id,"SELL",obs.observation_id,event.event_id,event.outcome,fill_time.isoformat(),self.mode,self.cohort,self.strict_evidence);self.store.save("execution_results",result);results.append(result.to_dict())
            except Exception as exc:
                acquired=books.get(code);source_ids=tuple(x.snapshot_id for x in getattr(acquired[2],"sources",())) if not isinstance(acquired,Exception) else ();rejected=ExecutionRejectionFactV51(day,executor.strategy_id,"SELL",code,position["decision_id"],source_ids,f"{type(exc).__name__}:{exc}",executed.isoformat(),self.mode,self.cohort,self.strict_evidence);self.store.save("execution_rejections",rejected);results.append(rejected.to_dict())
        first=results[0];return {"entity_id":first.get("execution_result_id") or first["rejection_id"],"execution_snapshot_ids":sorted({value[0].snapshot_id for value in books.values() if not isinstance(value,Exception)}),"results":results}
    def _notification(self,day,now,kind,stage_name):
        row=_one(self.root/kind/day,kind);entity_id=row.get("pool_id") or row.get("confirmation_id")
        if not entity_id:raise ContractViolation("notification business entity missing")
        from .notifications import V51NotificationService
        service=V51NotificationService(self.root,Path(__file__).resolve().parent/"production_ownership.json")
        receipt=service.send(trade_date=day,stage=stage_name,entity_id=entity_id,title=f"V5.1 {stage_name}",content=json.dumps(row,ensure_ascii=False,sort_keys=True),recorded_at=now.isoformat())
        return {"entity_id":receipt.receipt_id,"accepted":receipt.accepted}
    def _morning_notification(self,day,now):return self._notification(day,now,"morning_pools","morning_notification")
    def _confirmation_notification(self,day,now):return self._notification(day,now,"confirmations","confirmation_notification")
    def _stage_outcomes(self,day):
        rows=self._validated_runs(day)
        latest={}
        for row in sorted(rows,key=lambda x:(x["completed_at"],x["run_id"])):latest[row["task_name"]]=row
        return latest
    def _execution_stage_fact(self,day):
        folder=self.root/"stage_outcomes"/day;rows=[]
        for path in sorted(folder.glob("*.json")) if folder.exists() else ():
            row=_json(path)
            if row.get("stage")=="execution":
                self._validate_entity(day,row.get("stage_outcome_id",""));rows.append(row)
        if len(rows)!=1:raise ContractViolation("execution stage outcome missing or ambiguous")
        return rows[0]
    def _health(self,day,now):
        latest=self._stage_outcomes(day);required={"preflight","morning_observation","morning_pool","feature_freeze","confirmation","execution"};missing=sorted(required-set(latest));failed=sorted(x for x in required if x in latest and latest[x]["outcome"]!="SUCCESS")
        for name in required & set(latest):
            if latest[name]["outcome"]=="SUCCESS":self._validate_entity(day,latest[name]["entity_id"])
        verifier=ImmutableReadModelBuilder(self.root);observations=verifier._rows("execution_observations",day);results=verifier._rows("execution_results",day);rejections=verifier._rows("execution_rejections",day);stage_fact=self._execution_stage_fact(day)
        observation_ids={row["observation_id"] for row in observations};event_ids=set()
        for strategy in (BASELINE_STRATEGY_VERSION,CLOSESCAN_STRATEGY_VERSION):event_ids.update(row["event_id"] for row in StrategyPaperExecutorV51(self.root,strategy).ledger.events())
        for row in results:
            if row["observation_id"] not in observation_ids or row["paper_event_id"] not in event_ids:raise ContractViolation("execution result order/event lineage invalid")
        for row in observations:
            path=self.root/"snapshots"/day/f"{row['execution_snapshot_id']}.json"
            if not path.exists():raise ContractViolation("execution observation snapshot missing")
            self._snapshot(path)
        baseline=_one(self.root/"confirmations"/day,"baseline confirmation");close=_one(self.root/"closescan_selections"/day,"CloseScan selection")
        expected=[]
        if baseline.get("candidates"):expected.append(f"{BASELINE_STRATEGY_VERSION}:{baseline['confirmation_id']}:{baseline['candidates'][0]['code']}")
        if close.get("candidates"):expected.append(f"{CLOSESCAN_STRATEGY_VERSION}:{close['selection_id']}:{close['candidates'][0]['code']}")
        actual_audits={row["execution_result_id"] for row in results if row.get("side")=="BUY"}|{row["rejection_id"] for row in rejections if row.get("side")=="BUY"}
        if sorted(expected)!=sorted(stage_fact.get("intent_ids",[])) or set(stage_fact.get("audit_entity_ids",[]))!=actual_audits or stage_fact.get("intent_count")!=len(expected) or len(actual_audits)!=len(expected):raise ContractViolation("execution intent/audit lineage incomplete or conflicting")
        if stage_fact.get("outcome")=="FAIL_CLOSED":raise ContractViolation("execution stage infrastructure failed closed")
        ledgers={strategy:StrategyPaperExecutorV51(self.root,strategy).ledger.reconcile() for strategy in (BASELINE_STRATEGY_VERSION,CLOSESCAN_STRATEGY_VERSION)}
        pending=sum(len(StrategyPaperExecutorV51(self.root,strategy).ledger.pending_orders()) for strategy in (BASELINE_STRATEGY_VERSION,CLOSESCAN_STRATEGY_VERSION))
        if missing or failed or pending or not all(x["passed"] for x in ledgers.values()):raise ContractViolation(f"health incomplete missing={missing} failed={failed} pending={pending}")
        fact=HealthFactV51(day,now.isoformat(),tuple(sorted(latest[x]["run_id"] for x in required)),ledgers,pending,"PASSED");self.store.save("health_facts",fact);return {"entity_id":fact.health_id,"ledgers":ledgers}
    def _acceptance(self,day,now):
        latest=self._stage_outcomes(day);required={"preflight","morning_observation","morning_pool","feature_freeze","confirmation","execution","health"};missing=sorted(required-set(latest));failed=sorted(x for x in required if x in latest and latest[x]["outcome"]!="SUCCESS")
        if missing or failed:raise ContractViolation(f"acceptance incomplete missing={missing} failed={failed}")
        for name in required:self._validate_entity(day,latest[name]["entity_id"])
        stage_fact=self._execution_stage_fact(day);mapping={"ACTIVE_FLAT":"ACTIVE_FLAT","ALL_FILLED":"PASS","PARTIAL_FILL":"PASS","NO_STRICT_FILL":"NO_STRICT_FILL","EXECUTION_REJECTED":"EXECUTION_REJECTED","FAIL_CLOSED":"FAIL_CLOSED"};execution_acceptance=mapping.get(stage_fact["outcome"],"FAIL_CLOSED")
        run_ids=tuple(sorted(latest[x]["run_id"] for x in required));entities=tuple(sorted({*(latest[x]["entity_id"] for x in required if latest[x].get("entity_id")),*stage_fact.get("audit_entity_ids",())}));fact=AcceptanceFactV51(day,now.isoformat(),run_ids,entities,"PASS",execution_acceptance,"PENDING","PENDING","PRELIMINARY_ONLY");self.store.save("acceptance_facts",fact);return {"entity_id":fact.acceptance_id,"acceptance_phase":"PRELIMINARY_DAY",**fact.to_dict()}

    def _round_trip_acceptance(self,day,now):
        existing=[]
        for path in (self.root/"round_trip_acceptances").glob("*/*.json") if (self.root/"round_trip_acceptances").exists() else ():
            row=_json(path)
            if row.get("exit_trade_date")==day:existing.append(row)
        if len(existing)>1:raise ContractViolation("round-trip acceptance ambiguous for exit day")
        if existing:
            self._validate_entity(existing[0]["trade_date"],existing[0]["round_trip_acceptance_id"]);return {"entity_id":existing[0]["round_trip_acceptance_id"],"strict_day_accepted":True,**existing[0]}
        candidates=[]
        for path in sorted((self.root/"acceptance_facts").glob("*/*.json")) if (self.root/"acceptance_facts").exists() else ():
            row=_json(path)
            if row.get("real_window_acceptance")!="PRELIMINARY_ONLY" or row.get("trade_date")>=day:continue
            already=[]
            for candidate_path in (self.root/"round_trip_acceptances").glob("*/*.json") if (self.root/"round_trip_acceptances").exists() else ():
                candidate_row=_json(candidate_path)
                if candidate_row.get("preliminary_acceptance_id")==row.get("acceptance_id"):already.append(candidate_row)
            if not already:candidates.append(row)
        if len(candidates)!=1:raise ContractViolation("round-trip acceptance requires exactly one due preliminary day")
        preliminary=candidates[0];buy_day=preliminary["trade_date"];stage_rows=[]
        preliminary_runs=[x for x in self._validated_runs(buy_day) if x.get("task_name")=="acceptance" and x.get("outcome")=="SUCCESS" and x.get("entity_id")==preliminary.get("acceptance_id")]
        if len(preliminary_runs)!=1:raise ContractViolation("round-trip acceptance preliminary run lineage missing or ambiguous")
        exit_runs=[x for x in self._validated_runs(day) if x.get("task_name")=="next_open_exit" and x.get("outcome")=="SUCCESS"]
        if len(exit_runs)!=1:raise ContractViolation("round-trip acceptance requires successful next-open exit run")
        for path in (self.root/"stage_outcomes"/buy_day).glob("*.json"):
            row=_json(path)
            if row.get("stage")=="execution":stage_rows.append(row)
        if len(stage_rows)!=1:raise ContractViolation("round-trip execution stage missing or ambiguous")
        stage=stage_rows[0];trips=[];strategies=[];active_flat=stage.get("outcome")=="ACTIVE_FLAT"
        decisions={}
        if not active_flat:
            baseline=_one(self.root/"confirmations"/buy_day,"baseline confirmation");close=_one(self.root/"closescan_selections"/buy_day,"CloseScan selection")
            decisions={BASELINE_STRATEGY_VERSION:(baseline.get("confirmation_id"),baseline.get("candidates",[])),CLOSESCAN_STRATEGY_VERSION:(close.get("selection_id"),close.get("candidates",[]))}
        verifier=ImmutableReadModelBuilder(self.root);buy_results=verifier._rows("execution_results",buy_day);sell_results=verifier._rows("execution_results",day);buy_observations=verifier._rows("execution_observations",buy_day);sell_observations=verifier._rows("execution_observations",day);exit_decisions=verifier._rows("exit_decisions",day)
        for strategy in (BASELINE_STRATEGY_VERSION,CLOSESCAN_STRATEGY_VERSION):
            executor=StrategyPaperExecutorV51(self.root,strategy);ledger_trips=[x for x in executor.ledger.round_trips() if x["buy_trade_date"]==buy_day and x["sell_trade_date"]==day]
            for trip in ledger_trips:
                if trip["code"]=="" or not trip["buy_event_id"] or not trip["sell_event_id"]:raise ContractViolation("round-trip event lineage incomplete")
                expected_decision,expected_candidates=decisions[strategy]
                if trip["decision_id"]!=expected_decision or not expected_candidates or expected_candidates[0].get("code")!=trip["code"]:raise ContractViolation("round-trip candidate/decision lineage mismatch")
                buy_result=[x for x in buy_results if x["strategy_version"]==strategy and x["side"]=="BUY" and x["paper_event_id"]==trip["buy_event_id"]]
                sell_result=[x for x in sell_results if x["strategy_version"]==strategy and x["side"]=="SELL" and x["paper_event_id"]==trip["sell_event_id"]]
                if len(buy_result)!=1 or len(sell_result)!=1:raise ContractViolation("round-trip execution result lineage missing or ambiguous")
                buy_obs=[x for x in buy_observations if x["observation_id"]==buy_result[0]["observation_id"] and x["strategy_id"]==strategy and x["decision_id"]==expected_decision and x["code"]==trip["code"]]
                sell_obs=[x for x in sell_observations if x["observation_id"]==sell_result[0]["observation_id"] and x["strategy_id"]==strategy and x["code"]==trip["code"]]
                if len(buy_obs)!=1 or len(sell_obs)!=1:raise ContractViolation("round-trip observation lineage missing or ambiguous")
                exits=[x for x in exit_decisions if x["exit_decision_id"]==sell_obs[0]["decision_id"] and x["strategy_version"]==strategy and x["code"]==trip["code"] and x["position_decision_id"]==expected_decision and x["buy_observation_id"]==buy_obs[0]["observation_id"]]
                if len(exits)!=1:raise ContractViolation("round-trip exit/position lineage missing or ambiguous")
                trip_id=content_id("v51trip1",{"strategy_version":strategy,**trip});trips.append((strategy,trip_id,trip));strategies.append(strategy)
            if executor.ledger.state()["positions"]:raise ContractViolation("round-trip acceptance open position remains")
            if not executor.ledger.reconcile()["passed"]:raise ContractViolation("round-trip acceptance ledger reconciliation failed")
        if active_flat and trips:raise ContractViolation("ACTIVE_FLAT contains round trips")
        if not active_flat and not trips:raise ContractViolation("traded preliminary day missing completed round trip")
        if not active_flat:
            expected=strict_int(stage.get("result_count"),"result_count",0)
            if len(trips)!=expected:raise ContractViolation("round-trip count does not match filled buy count")
        pnl=sum(float(x[2]["net_pnl"]) for x in trips)
        fact=RoundTripAcceptanceFactV51(buy_day,day,now.isoformat(),preliminary["acceptance_id"],"ACTIVE_FLAT" if active_flat else "TRADED",len(trips),tuple(sorted(set(strategies))),tuple(x[1] for x in trips),tuple(x[2]["buy_event_id"] for x in trips),tuple(x[2]["sell_event_id"] for x in trips),str(round(pnl,2)),"PASS",self.mode,self.cohort,self.strict_evidence);self.store.save("round_trip_acceptances",fact);return {"entity_id":fact.round_trip_acceptance_id,"strict_day_accepted":True,**fact.to_dict()}
