"""Same-day recovery observation; never substitutes for the 09:25 mother pool."""
from __future__ import annotations
from datetime import datetime
import hashlib,html,json,os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .core import CHINA_TZ,ContractViolation
from .jobs import load_universe
from .sina_source import SinaRealtimeSource
from .tencent_source import TencentRealtimeSource
from .data_production import ConsensusAcquirer
from .market_state import MarketStateV1
from .funnel import CandidateFunnel
from .notification import _token
from .storage import V5FactStore

def _immutable(path,payload):
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"));path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
    try:os.link(tmp,path)
    except FileExistsError:
        if path.read_text(encoding="utf-8")!=raw:raise ContractViolation("recovery observation immutable collision")
    finally:tmp.unlink(missing_ok=True)

def run(root,*,now=None,transport=None):
    root=Path(root);current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat()
    if not ((13,0,0)<=(current.hour,current.minute,current.second)<=(13,10,0)):raise ContractViolation("recovery observation outside 13:00-13:10 window")
    universe=load_universe(root,day,as_of=current,require_native=True)
    result=ConsensusAcquirer(SinaRealtimeSource(),TencentRealtimeSource()).acquire(universe,stage="signal",now=current)
    if not result.accepted:raise ContractViolation("recovery observation dual-source consensus rejected")
    store=V5FactStore(root);store.save_snapshot(result.primary);market=MarketStateV1.from_snapshot(result.primary);store.save_market_state(market)
    funnel=CandidateFunnel().run(result.primary,market_state_id=market.market_state_id,market_valid=market.trade_allowed,stage="morning")
    candidates=list(funnel.candidates[:5]);payload={"schema_version":"v5-recovery-observation-v1","trade_date":day,"observed_at":current.isoformat(),"snapshot_id":result.primary.snapshot_id,"market_state_id":market.market_state_id,"source_consensus":result.report,"candidates":candidates,"strict_0925_sample":False,"eligible_for_confirmation":False,"eligible_for_paper":False,"research_locked":True}
    payload["observation_id"]="recovery1-"+hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:24]
    _immutable(root/"recovery_observations"/day/f"{payload['observation_id']}.json",payload)
    rows="".join(f"<li><b>{html.escape(x['name'])} {x['code']}</b> · 排名#{x['rank']} · 涨幅{float(x['change_pct']):.2f}%<br>理由：{html.escape('；'.join(x['reasons']))}<br>风险：{html.escape('；'.join(x['risks']))}</li>" for x in candidates)
    content=f"<h3>V5 午后恢复观察 {day}</h3><p><b>重要：</b>本次为13:01恢复观察，不是09:25严格早盘样本，不进入14:50确认或模拟买入。<br>市场状态：{html.escape(market.regime)}；覆盖与双源一致性已通过；research_locked。</p>"+(f"<ol>{rows}</ol>" if rows else "<p>当前没有股票通过观察漏斗。</p>")
    post=urlencode({"token":_token(root.parent/".env"),"title":f"V5午后恢复观察 {day}","content":content,"template":"html"}).encode();transport=transport or (lambda:json.loads(urlopen(Request("https://www.pushplus.plus/send",data=post,headers={"Content-Type":"application/x-www-form-urlencoded"}),timeout=15).read().decode()));response=transport()
    receipt={"schema_version":"v5-recovery-notification-v1","trade_date":day,"observation_id":payload["observation_id"],"response_code":response.get("code"),"outcome":"ACCEPTED" if response.get("code")==200 else "REJECTED","recorded_at":datetime.now(CHINA_TZ).isoformat()}
    _immutable(root/"recovery_notifications"/day/f"{payload['observation_id']}.json",receipt)
    if receipt["outcome"]!="ACCEPTED":raise RuntimeError("PushPlus recovery observation not accepted")
    return {"observation":payload,"receipt":receipt}
