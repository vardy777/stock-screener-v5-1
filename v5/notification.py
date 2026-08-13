"""V5-only PushPlus projection from final V5 facts; never recalculates candidates."""
from __future__ import annotations
from datetime import datetime
import hashlib,html,json,os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .core import CHINA_TZ,ContractViolation

def _latest(root,kind,day):
    files=sorted((Path(root)/kind/day).glob("*.json"))
    if not files:raise ContractViolation(f"V5 {kind} fact missing")
    return json.loads(files[-1].read_text(encoding="utf-8"))
def build_payload(root,trade_date,stage):
    acquisition=_latest(root,"acquisition",trade_date)
    if acquisition.get("accepted") is not True:raise ContractViolation("V5 acquisition not accepted")
    if stage=="morning":entity=_latest(root,"morning_pools",trade_date);parent=entity["pool_id"];title=f"V5早盘观察 {trade_date}"
    elif stage=="confirmation":entity=_latest(root,"confirmations",trade_date);parent=entity["confirmation_id"];title=f"V5尾盘确认 {trade_date}"
    else:raise ContractViolation("unsupported V5 notification stage")
    candidates=entity.get("candidates",[]);rows=[]
    for row in candidates[:5 if stage=="morning" else 3]:
        rows.append(f"<li><b>{html.escape(row['name'])} {row['code']}</b> · 排名#{row['rank']} · 涨幅{float(row['change_pct']):.2f}%<br>理由：{html.escape('、'.join(row.get('reasons',[])))}<br>风险：{html.escape('、'.join(row.get('risks',[])))}</li>")
    content=f"<h3>{title}</h3><p>V5实体：{parent}<br>行情快照：{entity.get('snapshot_id','')}<br>研究状态：research_locked</p>"+(f"<ol>{''.join(rows)}</ol>" if rows else "<p>没有候选通过V5严格门禁，不交易。</p>")+"<p>排序分不是上涨概率；仅用于本地模拟研究。</p>"
    payload={"title":title,"content":content,"template":"html","parent_entity_id":parent,"stage":stage,"trade_date":trade_date};payload["payload_sha256"]=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest();return payload
def _token(env_path):
    for line in Path(env_path).read_text(encoding="utf-8").splitlines():
        if line.startswith("PUSHPLUS_TOKEN="):return line.split("=",1)[1].strip()
    raise ContractViolation("PushPlus token missing")
def send(root,trade_date,stage,env_path,transport=None):
    payload=build_payload(root,trade_date,stage);receipt_path=Path(root)/"notifications"/trade_date/f"{stage}.json"
    if receipt_path.exists():
        prior=json.loads(receipt_path.read_text(encoding="utf-8"))
        if prior.get("outcome")=="ACCEPTED" and prior.get("payload_sha256")==payload["payload_sha256"]:return prior
        raise ContractViolation("V5 notification immutable collision")
    token=_token(env_path);post=urlencode({"token":token,"title":payload["title"],"content":payload["content"],"template":"html"}).encode();transport=transport or (lambda:json.loads(urlopen(Request("https://www.pushplus.plus/send",data=post,headers={"Content-Type":"application/x-www-form-urlencoded"}),timeout=15).read().decode()))
    response=transport();accepted=response.get("code")==200
    receipt={"schema_version":"v5-notification-receipt-v1","parent_entity_id":payload["parent_entity_id"],"payload_sha256":payload["payload_sha256"],"stage":stage,"trade_date":trade_date,"outcome":"ACCEPTED" if accepted else "REJECTED","response_code":response.get("code"),"recorded_at":datetime.now(CHINA_TZ).isoformat()}
    receipt_path.parent.mkdir(parents=True,exist_ok=True);tmp=receipt_path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")),encoding="utf-8");os.replace(tmp,receipt_path)
    if not accepted:raise RuntimeError("PushPlus did not return 200/ACCEPTED")
    return receipt
