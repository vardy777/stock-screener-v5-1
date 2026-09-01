"""Reliable V5-native universe refresh; partial pages are never production facts."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import dataclass
from datetime import datetime,time as wall_time
import hashlib,json,math,os,threading,time
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .core import CHINA_TZ,ContractViolation
from .eastmoney_source import UNIVERSE_FILTER
from .universe import UniverseV1,eligible

ENDPOINTS=("https://push2delay.eastmoney.com","https://push2.eastmoney.com","https://82.push2.eastmoney.com","https://72.push2.eastmoney.com")
DEFAULT_OVERALL_BUDGET_SECONDS=75
DEFAULT_CONCURRENCY=8
CHECKPOINT_CONTRACT="eastmoney-universe-directory-f12-v1"
@dataclass(frozen=True)
class DirectorySource:
 source_id:str;provider_identity:str;endpoints:tuple[str,...];independent_provider:bool=False
EASTMONEY_SOURCE=DirectorySource("eastmoney_realtime_market_directory","eastmoney",ENDPOINTS,False)
def independent_sources(sources):
 sources=tuple(sources);primary_identities={s.provider_identity for s in sources if not s.independent_provider}
 return tuple(sorted({s.provider_identity for s in sources if s.independent_provider and s.provider_identity not in primary_identities}))
def _fetch(url,timeout):
 request=Request(url,headers={"Referer":"https://quote.eastmoney.com/","User-Agent":"Mozilla/5.0"})
 with urlopen(request,timeout=timeout) as response:return json.loads(response.read().decode("utf-8"))
def _atomic_json(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"));tmp=path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp");tmp.write_text(raw,encoding="utf-8");os.replace(tmp,path)
def _url(endpoint,page,page_size):
 # Pagination must use a stable identifier sort.  Sorting by live change (f3)
 # lets symbols move between pages while a checkpointed capture is resumed,
 # producing duplicates and omissions even when every page is present.
 query=urlencode({"pn":page,"pz":page_size,"po":1,"np":1,"fltt":2,"invt":2,"fid":"f12","fs":UNIVERSE_FILTER,"fields":"f12"});return endpoint+"/api/qt/clist/get?"+query

def fetch_codes(*,fetch_json=None,timeout=5,page_size=500,overall_budget_seconds=DEFAULT_OVERALL_BUDGET_SECONDS,monotonic=None,sleeper=None,retries=2,endpoints=None,return_diagnostics=False,concurrency=DEFAULT_CONCURRENCY,checkpoint_dir=None,source=EASTMONEY_SOURCE):
 fetch_json=fetch_json or _fetch;monotonic=monotonic or time.monotonic;sleeper=sleeper or time.sleep;endpoints=tuple(source.endpoints if endpoints is None else endpoints)
 if not endpoints:raise ContractViolation("universe directory source has no endpoint")
 started=monotonic();deadline=started+float(overall_budget_seconds);failures=[];lock=threading.Lock();checkpoint=Path(checkpoint_dir) if checkpoint_dir else None;resumed=[]
 def remaining():
  value=deadline-monotonic()
  if value<=0:
   exc=TimeoutError("universe refresh exceeded overall budget");exc.diagnostics={"endpoint_failures":list(failures),"budget_seconds":float(overall_budget_seconds),"provider_identity":source.provider_identity};raise exc
  return value
 def parse(payload,page):
  data=payload.get("data",{}) if isinstance(payload,dict) else {}
  if payload.get("rc")!=0 or not isinstance(data.get("diff"),list):raise ContractViolation(f"universe provider payload invalid on page {page}")
  total=int(data.get("total",0) or 0)
  if not 1<=total<=10000:raise ContractViolation("universe declared total outside safety bound")
  codes=[str(row.get("f12","")).zfill(6) for row in data["diff"]]
  if not codes:raise ContractViolation(f"universe pagination incomplete: empty page {page} expected_total={total}")
  return {"page":page,"declared_total":total,"codes":codes}
 def cached(page):
  if checkpoint is None:return None
  path=checkpoint/f"page-{page:04d}.json"
  try:
   row=json.loads(path.read_text(encoding="utf-8"))
   if row.get("checkpoint_contract")!=CHECKPOINT_CONTRACT or row.get("source_id")!=source.source_id or row.get("page")!=page:return None
   resumed.append(page);return {"page":page,"declared_total":int(row["declared_total"]),"codes":list(row["codes"])}
  except (OSError,ValueError,KeyError,TypeError):return None
 def one(page):
  hit=cached(page)
  if hit is not None:return hit
  last=None
  # Every configured host belongs to the same provider family, but each is a
  # legitimate transport failover.  A page must try the complete host ring at
  # least once; otherwise its page-number-based starting offset can
  # permanently exclude the only healthy host on every recovery run.
  attempts=max(1,int(retries)+1,len(endpoints))
  for attempt in range(attempts):
   allowance=remaining();endpoint=endpoints[(page+attempt-1)%len(endpoints)];began=monotonic()
   try:
    row=parse(fetch_json(_url(endpoint,page,page_size),min(float(timeout),max(.1,allowance))),page)
    if checkpoint:_atomic_json(checkpoint/f"page-{page:04d}.json",{**row,"checkpoint_contract":CHECKPOINT_CONTRACT,"source_id":source.source_id,"provider_identity":source.provider_identity})
    return row
   except ContractViolation:raise
   except (HTTPError,URLError,TimeoutError,ConnectionError,OSError,RemoteDisconnected,RuntimeError) as exc:
    last=exc
    with lock:failures.append({"page":page,"endpoint":endpoint,"provider_identity":source.provider_identity,"attempt":attempt+1,"error":type(exc).__name__,"elapsed_seconds":round(monotonic()-began,6)})
    if attempt<attempts-1:sleeper(min(.2*(attempt+1),max(0,remaining())))
  exc=RuntimeError(f"universe page {page} unavailable: {type(last).__name__}");exc.diagnostics={"failed_page":page,"endpoint_failures":list(failures),"budget_seconds":float(overall_budget_seconds),"provider_identity":source.provider_identity};raise exc from last
 first=one(1);width=len(first["codes"])
 if width<1:raise ContractViolation(f"universe pagination incomplete: received=0 expected={first['declared_total']}")
 total=first["declared_total"];page_count=math.ceil(total/width)
 if page_count>100:raise ContractViolation("universe page count outside safety bound")
 pages={1:first};missing=list(range(2,page_count+1));workers=max(1,min(int(concurrency),len(missing) or 1))
 with ThreadPoolExecutor(max_workers=workers,thread_name_prefix="universe-page") as pool:
  futures={pool.submit(one,page):page for page in missing}
  try:
   for future in as_completed(futures):pages[futures[future]]=future.result()
  except Exception:
   for future in futures:future.cancel()
   raise
 ordered=[]
 for page in range(1,page_count+1):
  row=pages.get(page)
  if row is None or row["declared_total"]!=total:raise ContractViolation(f"universe pagination incomplete: missing page {page}")
  ordered.extend(row["codes"])
 if len(ordered)<total:raise ContractViolation(f"universe pagination incomplete: received={len(ordered)} expected={total}")
 ordered=ordered[:total]
 if len(set(ordered))!=len(ordered):raise ContractViolation("universe pagination contains duplicate codes")
 values=sorted(code for code in ordered if eligible(code))
 if not values:raise ContractViolation("universe provider returned no eligible codes")
 diagnostics={"source_id":source.source_id,"provider_identity":source.provider_identity,"independent_provider":source.independent_provider,"endpoint_hosts_are_independent_sources":False,"endpoint_failures":sorted(failures,key=lambda x:(x["page"],x["attempt"])),"declared_total":total,"pages":page_count,"actual_page_length":width,"concurrency":workers,"resumed_pages":sorted(set(resumed)),"elapsed_seconds":round(monotonic()-started,6),"budget_seconds":float(overall_budget_seconds)}
 return (values,diagnostics) if return_diagnostics else values

def _previous(root,day,*,as_of=None):
 candidates=[]
 for directory in (Path(root)/"universes").iterdir() if (Path(root)/"universes").exists() else ():
  if directory.name>day:continue
  for path in directory.glob("*.json"):
   row=json.loads(path.read_text(encoding="utf-8"));created=datetime.fromisoformat(row["created_at"])
   if created.tzinfo is None:raise ContractViolation("prior universe time requires timezone")
   if as_of is None or created.astimezone(CHINA_TZ)<=as_of.astimezone(CHINA_TZ):candidates.append((created,row.get("universe_id",path.name),row))
 return max(candidates,key=lambda x:(x[0],x[1]))[2] if candidates else None
def _published_today(root,day,as_of):
 row=_previous(root,day,as_of=as_of)
 return row if row and row.get("trade_date")==day and EASTMONEY_SOURCE.source_id in row.get("sources",[]) else None
def _attempt(root,day,value):
 unsigned=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"));identity="universe-attempt1-"+hashlib.sha256(unsigned.encode()).hexdigest()[:24];path=Path(root)/"universe_attempts"/day/f"{identity}.json";_atomic_json(path,{**value,"attempt_id":identity}) if not path.exists() else None;return path

def refresh(root,*,now=None,fetch_json=None,minimum_prior_ratio=.98,maximum_churn_ratio=.02,overall_budget_seconds=DEFAULT_OVERALL_BUDGET_SECONDS,monotonic=None,concurrency=DEFAULT_CONCURRENCY,wall_clock=None):
 initial=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);clock=wall_clock or (lambda:initial);current=initial;day=current.date().isoformat();root=Path(root);cutoff=datetime.combine(current.date(),wall_time(9,20),tzinfo=CHINA_TZ);existing=_published_today(root,day,current)
 if existing:return {"universe_id":existing["universe_id"],"trade_date":day,"count":len(existing["codes"]),"checks":{"already_published":True},"diagnostics":{"idempotent_reuse":True},"path":str(root/"universes"/day/f"{existing['universe_id']}.json")}
 started=current.isoformat();diagnostics={};seconds_to_cutoff=(cutoff-clock().astimezone(CHINA_TZ)).total_seconds()
 try:
  if seconds_to_cutoff<=0:raise TimeoutError("universe refresh publication cutoff 09:20 exceeded")
  codes,diagnostics=fetch_codes(fetch_json=fetch_json,overall_budget_seconds=min(float(overall_budget_seconds),seconds_to_cutoff),monotonic=monotonic,return_diagnostics=True,concurrency=concurrency,checkpoint_dir=root/".universe_refresh_staging"/day/EASTMONEY_SOURCE.source_id)
  if fetch_json is None:
   from .tencent_source import active_codes
   count=len(codes);codes=active_codes(codes);diagnostics.update({"directory_count":count,"active_count":len(codes),"active_filter":"tencent_explicit_delisted_marker"})
  prior=_previous(root,day,as_of=current);checks={"provider_nonempty":bool(codes),"pagination_complete":True}
  if prior:
   old=set(prior["codes"]);new=set(codes);legacy="legacy_daily_archive_seed_migration" in prior.get("sources",[]);correction=diagnostics.get("active_filter")=="tencent_explicit_delisted_marker" and new<=old and len(new)>=len(old)*.90
   checks["minimum_prior_count"]=len(new)>=len(old)*minimum_prior_ratio or correction
   if correction:diagnostics["scope_correction"]="REMOVE_TENCENT_EXPLICIT_DELISTED_ONLY"
   if legacy:
    checks["legacy_seed_retention"]=len(old&new)/max(len(old),1)>=.995;checks["migration_is_expansion_only"]=len(old-new)==0;checks["bounded_churn"]=checks["legacy_seed_retention"] and checks["migration_is_expansion_only"];diagnostics["migration_mode"]="legacy_seed_to_native_directory"
   else:
    star=not any(x.startswith(("688","689")) for x in old) and any(x.startswith(("688","689")) for x in new) and not(old-new);checks["bounded_churn"]=len(old^new)/max(len(old),1)<=maximum_churn_ratio or star or correction
    if star:diagnostics["scope_upgrade"]="ADD_STAR_MARKET_RETAIN_ALL_PRIOR_CODES"
  if not all(checks.values()):raise ContractViolation("daily universe anomaly gate rejected refresh")
  published_at=clock().astimezone(CHINA_TZ)
  if published_at>cutoff:raise TimeoutError("universe refresh publication cutoff 09:20 exceeded")
  universe=UniverseV1.build(trade_date=day,created_at=published_at,codes=codes,sources=[EASTMONEY_SOURCE.source_id,"tencent_active_listing_filter","prior_universe_anomaly_gate"]);path=universe.save(root);_attempt(root,day,{"schema_version":"v5-universe-refresh-attempt-v1","trade_date":day,"started_at":started,"recorded_at":clock().astimezone(CHINA_TZ).isoformat(),"outcome":"SUCCESS","universe_id":universe.universe_id,"checks":checks,"diagnostics":diagnostics});return {"universe_id":universe.universe_id,"trade_date":day,"count":len(universe.codes),"checks":checks,"diagnostics":diagnostics,"path":str(path)}
 except Exception as exc:
  diagnostics=getattr(exc,"diagnostics",diagnostics);_attempt(root,day,{"schema_version":"v5-universe-refresh-attempt-v1","trade_date":day,"started_at":started,"recorded_at":clock().astimezone(CHINA_TZ).isoformat(),"outcome":"FAILED","error_type":type(exc).__name__,"error":str(exc),"diagnostics":diagnostics});raise
