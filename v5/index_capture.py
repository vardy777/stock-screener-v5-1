"""Non-blocking dual-source CSI300 capture for the 14:49 research regime fact."""
from __future__ import annotations
from datetime import datetime
from urllib.request import Request,urlopen
from pathlib import Path
import hashlib,json,re,os
from .core import CHINA_TZ,ContractViolation
from .index_benchmark import BENCHMARK_CODE,source_observation,save
def _fetch(url,encoding,referer,timeout):
    with urlopen(Request(url,headers={"Referer":referer,"User-Agent":"Mozilla/5.0"}),timeout=timeout) as response:return response.read().decode(encoding,errors="replace")
class SinaCSI300Source:
    name="sina_csi300_realtime"
    def __init__(self,fetch_text=None):self.fetch_text=fetch_text or (lambda url,timeout:_fetch(url,"gbk","https://finance.sina.com.cn",timeout))
    def capture(self,now):
        text=self.fetch_text("https://hq.sinajs.cn/list=sh000300",10);match=re.search(r'var hq_str_sh000300="(.*)";',text)
        if not match:raise ContractViolation("Sina CSI300 response missing")
        f=match.group(1).split(",");observed=datetime.fromisoformat(f"{f[30]}T{f[31]}+08:00");snapshot="idxresp1-"+hashlib.sha256(text.encode()).hexdigest()[:24]
        return source_observation(observed_at=observed.isoformat(),previous_close=float(f[2]),last_price=float(f[3]),provider=self.name,source_snapshot_id=snapshot)
class TencentCSI300Source:
    name="tencent_csi300_realtime"
    def __init__(self,fetch_text=None):self.fetch_text=fetch_text or (lambda url,timeout:_fetch(url,"gb18030","https://finance.qq.com",timeout))
    def capture(self,now):
        text=self.fetch_text("https://qt.gtimg.cn/q=sh000300",10);match=re.search(r'v_sh000300="(.*)";',text)
        if not match:raise ContractViolation("Tencent CSI300 response missing")
        f=match.group(1).split("~");observed=datetime.strptime(f[30],"%Y%m%d%H%M%S").replace(tzinfo=CHINA_TZ);snapshot="idxresp1-"+hashlib.sha256(text.encode()).hexdigest()[:24]
        return source_observation(observed_at=observed.isoformat(),previous_close=float(f[4]),last_price=float(f[3]),provider=self.name,source_snapshot_id=snapshot)
def _save_run(root,day,value):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"));entity_id="idxrun1-"+hashlib.sha256(raw.encode()).hexdigest()[:24];path=Path(root)/"index_benchmark_runs"/day/f"{entity_id}.json";path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
    try:os.link(tmp,path)
    except FileExistsError:
        if path.read_text(encoding="utf-8")!=raw:raise ContractViolation("index capture run immutable collision")
    finally:tmp.unlink(missing_ok=True)
    return value|{"run_id":entity_id}
def capture(root,*,now,sources=None):
    current=now.astimezone(CHINA_TZ);day=current.date().isoformat();sources=sources or (SinaCSI300Source(),TencentCSI300Source());observations=[];errors=[]
    for source in sources:
        try:observations.append(source.capture(current))
        except Exception as exc:errors.append({"provider":getattr(source,"name",type(source).__name__),"error":f"{type(exc).__name__}: {exc}"})
    if len(observations)!=2:errors.append({"provider":"dual_source_consensus","error":f"required 2 independent observations, received {len(observations)}"})
    try:
        fact=save(root,trade_date=day,observed_at=current,source_observations=observations) if len(observations)==2 else None;status=fact["status"] if fact else "UNKNOWN";benchmark_id=fact["index_benchmark_id"] if fact else ""
    except Exception as exc:errors.append({"provider":"dual_source_consensus","error":f"{type(exc).__name__}: {exc}"});status="UNKNOWN";benchmark_id=""
    return _save_run(root,day,{"schema_version":"v5-index-benchmark-capture-run-v1","trade_date":day,"recorded_at":current.isoformat(),"status":status,"index_benchmark_id":benchmark_id,"source_observation_ids":[row["source_observation_id"] for row in observations],"errors":errors,"non_blocking_research_gate":True})
