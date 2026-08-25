"""Pre-registered CSI 300 point-in-time decline benchmark facts."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import hashlib,json,os
from .core import CHINA_TZ,ContractViolation
BENCHMARK_CODE="000300";BENCHMARK_NAME="沪深300";DECLINE_THRESHOLD=-0.02;POLICY_ID="v5-index-decline-csi300-close-to-point-v1"
def _canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def _id(value):return "idxbench1-"+hashlib.sha256(_canonical(value).encode()).hexdigest()[:24]
def source_observation(*,observed_at,previous_close,last_price,provider,source_snapshot_id):
    value={"schema_version":"v5-index-source-observation-v1","benchmark_code":BENCHMARK_CODE,"observed_at":str(observed_at),"previous_close":float(previous_close),"last_price":float(last_price),"provider":str(provider),"source_snapshot_id":str(source_snapshot_id)}
    return value|{"source_observation_id":"idxsrc1-"+hashlib.sha256(_canonical(value).encode()).hexdigest()[:24]}
def save(root,*,trade_date,observed_at,source_observations):
    observed=datetime.fromisoformat(observed_at) if isinstance(observed_at,str) else observed_at
    if observed.tzinfo is None or observed.utcoffset() is None:raise ContractViolation("index benchmark timestamp timezone required")
    observed=observed.astimezone(CHINA_TZ)
    sources=sorted((dict(row) for row in source_observations),key=lambda row:row.get("provider",""))
    if observed.date().isoformat()!=trade_date or len(sources)!=2 or len({row.get("provider") for row in sources})!=2:raise ContractViolation("two independent CSI300 benchmark sources required")
    changes=[]
    for row in sources:
        declared=row.get("source_observation_id","");unsigned={key:value for key,value in row.items() if key!="source_observation_id"};expected="idxsrc1-"+hashlib.sha256(_canonical(unsigned).encode()).hexdigest()[:24]
        if declared!=expected:raise ContractViolation("CSI300 source observation content-address mismatch")
        if row.get("benchmark_code")!=BENCHMARK_CODE or float(row.get("previous_close",0))<=0 or float(row.get("last_price",0))<=0 or not row.get("source_snapshot_id"):raise ContractViolation("strict CSI300 benchmark inputs required")
        source_time=datetime.fromisoformat(row["observed_at"])
        if source_time.tzinfo is None or source_time.astimezone(CHINA_TZ).date().isoformat()!=trade_date or abs((observed-source_time.astimezone(CHINA_TZ)).total_seconds())>15:raise ContractViolation("CSI300 source point-time mismatch")
        changes.append(float(row["last_price"])/float(row["previous_close"])-1)
    if abs(changes[0]-changes[1])>.002:raise ContractViolation("CSI300 source change disagreement")
    change=max(changes);value={"schema_version":"v5-index-benchmark-v2","policy_id":POLICY_ID,"benchmark_code":BENCHMARK_CODE,"benchmark_name":BENCHMARK_NAME,"trade_date":trade_date,"observed_at":observed.isoformat(),"source_observations":sources,"change":change,"decline_threshold":DECLINE_THRESHOLD,"consensus_rule":"both independent source changes within 0.2 percentage points; conservative max change","status":"VERIFIED_DECLINE" if all(value<=DECLINE_THRESHOLD for value in changes) else "VERIFIED_NOT_DECLINE"}
    entity_id=_id(value);path=Path(root)/"index_benchmarks"/trade_date/f"{entity_id}.json";path.parent.mkdir(parents=True,exist_ok=True);raw=_canonical(value);tmp=path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
    try:os.link(tmp,path)
    except FileExistsError:
        if path.read_text(encoding="utf-8")!=raw:raise ContractViolation("index benchmark immutable collision")
    finally:tmp.unlink(missing_ok=True)
    return value|{"index_benchmark_id":entity_id}
def resolve(root,trade_date,*,as_of):
    cutoff=datetime.fromisoformat(as_of) if isinstance(as_of,str) else as_of
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:raise ContractViolation("index benchmark as_of timezone required")
    rows=[]
    for path in (Path(root)/"index_benchmarks"/trade_date).glob("idxbench1-*.json"):
        value=json.loads(path.read_text(encoding="utf-8"))
        if path.stem!=_id(value) or value.get("policy_id")!=POLICY_ID or value.get("benchmark_code")!=BENCHMARK_CODE:raise ContractViolation("index benchmark content-address mismatch")
        if datetime.fromisoformat(value["observed_at"])<=cutoff.astimezone(CHINA_TZ):rows.append(value|{"index_benchmark_id":path.stem})
    if not rows:return {"status":"UNKNOWN","index_benchmark_id":"","large_index_decline":False,"policy_id":POLICY_ID}
    selected=max(rows,key=lambda row:(row["observed_at"],row["index_benchmark_id"]));return selected|{"large_index_decline":selected["status"]=="VERIFIED_DECLINE"}
