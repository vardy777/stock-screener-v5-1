"""Real V5.1 market adapters; production paths never use fixtures or caches."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from shared_core.core import CHINA_TZ,ContractViolation
from shared_core.data_production import ConsensusAcquirer
from shared_core.market_snapshot import MarketSnapshotV1
from shared_core.sina_source import SinaRealtimeSource
from shared_core.tencent_source import TencentRealtimeSource
from shared_core.universe import UniverseV1
from shared_core.universe_refresh import fetch_codes,EASTMONEY_SOURCE,ENDPOINTS
from urllib.parse import urlencode
from urllib.request import Request,urlopen
import base64,hashlib,json,math
from shared_core.eastmoney_source import UNIVERSE_FILTER

STAGE_MAP={"morning_observation":"morning","morning_0935":"morning","signal":"signal","buy_execution":"confirmation","sell_execution":"sell"}

class _SourceAdapter:
    def __init__(self,source):self.source=source;self.name=source.name
    def capture(self,codes,*,stage,now):
        upstream=STAGE_MAP.get(stage)
        if upstream is None:raise ContractViolation("unsupported V5.1 provider stage")
        raw=self.source.capture(codes,stage=upstream,now=now)
        return MarketSnapshotV1.build(trade_date=raw.trade_date,session=stage,batch_started_at=raw.batch_started_at,batch_completed_at=raw.batch_completed_at,quotes=raw.quotes,expected_codes=raw.quality.expected_codes)

@dataclass(frozen=True)
class ProviderDiagnostic:
    recorded_at:str;strict_evidence:bool;stage:str;accepted:bool;coverage:float;consensus:float;elapsed_seconds:float;report:dict

class V51MarketDataProvider:
    """Sina/Tencent dual-source adapter with V5.1 session identities."""
    def __init__(self,sina=None,tencent=None):
        self.sina=_SourceAdapter(sina or SinaRealtimeSource())
        self.tencent=_SourceAdapter(tencent or TencentRealtimeSource())
        self.consensus=ConsensusAcquirer(self.sina,self.tencent)
    def acquire(self,codes,*,trade_date,stage,now):
        if now.tzinfo is None:raise ContractViolation("provider current time must be aware")
        universe=UniverseV1.build(trade_date=trade_date,created_at=now,codes=codes,sources=["v5.1_persistent_master"])
        result=self.consensus.acquire(universe,stage=stage,now=now)
        if not result.accepted or result.primary is None:raise ContractViolation("V5.1 dual-source quality rejected")
        return result
    def smoke(self,codes,*,now=None):
        current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);started=monotonic();rows={}
        for source in (self.sina,self.tencent):
            began=monotonic()
            try:
                snap=source.capture(list(codes),stage="morning_observation",now=current)
                quote=snap.quotes[0] if snap.quotes else None
                rows[source.name]={"transport":"OK","provider_family":source.name.split("_")[0],"coverage":snap.quality.coverage,"snapshot_id":snap.snapshot_id,"completed_at":snap.batch_completed_at,"quote_timestamp":quote.provider_time if quote else None,"bid":quote.bid1 if quote else None,"bid_depth":quote.bid1_volume if quote else None,"ask":quote.ask1 if quote else None,"ask_depth":quote.ask1_volume if quote else None,"latency_seconds":round(monotonic()-began,6)}
            except Exception as exc:rows[source.name]={"transport":"FAILED","error":f"{type(exc).__name__}: {exc}","latency_seconds":round(monotonic()-began,6)}
        return ProviderDiagnostic(current.isoformat(),False,"NON_STRICT_DIAGNOSTIC",all(x["transport"]=="OK" for x in rows.values()),min((x.get("coverage",0) for x in rows.values()),default=0),0.0,round(monotonic()-started,6),rows)

class EastmoneyMasterDirectory:
    """Current approved directory bootstrap; all Eastmoney hosts are one family."""
    provider_family="eastmoney"
    source_id=EASTMONEY_SOURCE.source_id
    def discover(self):
        started=monotonic();total_budget_seconds=75
        codes,diagnostics=fetch_codes(return_diagnostics=True)
        if monotonic()-started>=total_budget_seconds:raise RuntimeError("master directory total budget exhausted after code discovery")
        wanted=set(codes);records={};page_size=500;page_count=None;raw_responses=[]
        for page in range(1,101):
            if monotonic()-started>=total_budget_seconds:raise RuntimeError(f"master directory total budget exhausted at page {page}")
            query=urlencode({"pn":page,"pz":page_size,"po":1,"np":1,"fltt":2,"invt":2,"fid":"f12","fs":UNIVERSE_FILTER,"fields":"f12,f14,f26"});payload=None;last=None
            for attempt in range(len(ENDPOINTS)):
                if monotonic()-started>=total_budget_seconds:break
                endpoint=ENDPOINTS[(page+attempt)%len(ENDPOINTS)];request=Request(endpoint+"/api/qt/clist/get?"+query,headers={"Referer":"https://quote.eastmoney.com/","User-Agent":"Mozilla/5.0"})
                try:
                    with urlopen(request,timeout=8) as response:
                        raw_body=response.read();candidate=json.loads(raw_body.decode("utf-8"));raw_digest=hashlib.sha256(raw_body).hexdigest()
                    if candidate.get("rc")==0 and isinstance((candidate.get("data") or {}).get("diff"),list):payload=candidate;break
                except (OSError,RuntimeError) as exc:last=exc
            if payload is None:raise RuntimeError(f"master directory page {page} unavailable: {type(last).__name__}") from last
            data=payload.get("data") or {};rows=data.get("diff") or []
            response_key=f"eastmoney-page-{page}-{raw_digest}";raw_responses.append({"endpoint":endpoint+"/api/qt/clist/get","retrieved_at":datetime.now(CHINA_TZ).isoformat(),"raw_sha256":raw_digest,"raw_content_b64":base64.b64encode(raw_body).decode("ascii"),"record_count":len(rows),"response_key":response_key})
            if payload.get("rc")!=0:raise ContractViolation("master directory identity payload invalid")
            if not rows:break
            if page_count is None:page_count=math.ceil(int(data.get("total",0) or 0)/len(rows))
            for row in rows:
                code=str(row.get("f12","")).zfill(6);name=str(row.get("f14","")).strip();raw_listed=row.get("f26","")
                try:listed=str(int(float(raw_listed)))
                except (TypeError,ValueError):listed=str(raw_listed).replace("-","")
                if code in wanted and name and len(listed)==8 and listed.isdigit():records[code]={"code":code,"name":name,"listing_date":f"{listed[:4]}-{listed[4:6]}-{listed[6:]}","source_response_key":response_key}
            if len(records)>=len(wanted) or (page_count is not None and page>=page_count):break
        missing=wanted-set(records)
        # New/subscription symbols with no declared listing date are not yet
        # eligible identities.  They are explicitly excluded, never assigned
        # a fabricated date, and become eligible only after the provider
        # publishes complete identity metadata.
        return tuple(records[x] for x in sorted(records)),{**diagnostics,"provider_family":self.provider_family,"official_independent_source":False,"identity_records":len(records),"excluded_missing_identity_metadata":sorted(missing),"raw_responses":raw_responses}
