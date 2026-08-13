"""V5-only PushPlus projection from final V5 facts; never recalculates candidates."""
from __future__ import annotations
from datetime import datetime
import hashlib,html,json,os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .core import CHINA_TZ,ContractViolation
from .fact_reader import latest

def _latest(root,kind,day,*,as_of=None):
    return latest(root,kind,day,as_of=as_of)
def _acquisition(root,day,stage,*,as_of=None):
    return latest(root,"acquisition",day,predicate=lambda row:row.get("stage")==stage,as_of=as_of)
def build_payload(root,trade_date,stage,*,as_of=None):
    acquisition=_acquisition(root,trade_date,"morning" if stage=="morning" else "signal",as_of=as_of)
    if acquisition.get("accepted") is not True:raise ContractViolation("V5 acquisition not accepted")
    if stage=="morning":entity=_latest(root,"morning_pools",trade_date,as_of=as_of);parent=entity["pool_id"];title=f"V5早盘观察 {trade_date}";action="早盘候选只观察，不买入；等待14:49冻结和14:50同母池确认"
    elif stage=="confirmation":entity=_latest(root,"confirmations",trade_date,as_of=as_of);parent=entity["confirmation_id"];title=f"V5尾盘确认 {trade_date}";action=("存在尾盘确认候选，仅进入本地严格模拟，不发送券商订单" if entity.get("candidates") else "没有候选通过尾盘确认，保持空仓")
    else:raise ContractViolation("unsupported V5 notification stage")
    if acquisition.get("selected_snapshot_id")!=entity.get("snapshot_id"):raise ContractViolation("V5 notification snapshot lineage mismatch")
    candidates=entity.get("candidates",[]);rows=[]
    for row in candidates[:5 if stage=="morning" else 3]:
        entry=(f"冻结卖一参考 ¥{float(row['ask1']):.2f}；仅按14:50窗口本地模拟" if stage=="confirmation" and row.get("ask1") else "早盘观察，不展示买价")
        rows.append(f"<li><b>{html.escape(row['name'])} {row['code']}</b> · 排名#{row['rank']} · 涨幅{float(row['change_pct']):.2f}%<br><b>理由：</b>{html.escape('；'.join(row.get('reasons',[])))}<br><b>风险：</b>{html.escape('；'.join(row.get('risks',[])))}<br><b>执行：</b>{html.escape(entry)}；下一交易日09:30后按买一和滑点模拟卖出，当前不预测卖价</li>")
    content=f"<h3>{title}</h3><p><b>今日结论：</b>{html.escape(action)}<br>V5实体：{parent}<br>行情快照：{entity.get('snapshot_id','')}<br>研究状态：research_locked</p>"+(f"<ol>{''.join(rows)}</ol>" if rows else "<p>当前没有推荐股票。空仓是有效决策，不使用残缺行情或旧候选凑数。</p>")+"<p>排序分不是上涨概率；仅用于本地模拟研究，不连接券商。</p>"
    payload={"title":title,"content":content,"template":"html","parent_entity_id":parent,"stage":stage,"trade_date":trade_date};payload["payload_sha256"]=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest();return payload
def _token(env_path):
    for line in Path(env_path).read_text(encoding="utf-8").splitlines():
        if line.startswith("PUSHPLUS_TOKEN="):return line.split("=",1)[1].strip()
    raise ContractViolation("PushPlus token missing")
def send(root,trade_date,stage,env_path,transport=None,*,as_of=None):
    payload=build_payload(root,trade_date,stage,as_of=as_of);receipt_path=Path(root)/"notifications"/trade_date/f"{stage}.json"
    if receipt_path.exists():
        prior=json.loads(receipt_path.read_text(encoding="utf-8"))
        if prior.get("outcome")=="ACCEPTED" and prior.get("payload_sha256")==payload["payload_sha256"]:return prior
        raise ContractViolation("V5 notification immutable collision")
    token=_token(env_path);post=urlencode({"token":token,"title":payload["title"],"content":payload["content"],"template":"html"}).encode();transport=transport or (lambda:json.loads(urlopen(Request("https://www.pushplus.plus/send",data=post,headers={"Content-Type":"application/x-www-form-urlencoded"}),timeout=15).read().decode()))
    response=transport();accepted=response.get("code")==200
    receipt={"schema_version":"v5-notification-receipt-v1","parent_entity_id":payload["parent_entity_id"],"payload_sha256":payload["payload_sha256"],"stage":stage,"trade_date":trade_date,"outcome":"ACCEPTED" if accepted else "REJECTED","response_code":response.get("code"),"recorded_at":datetime.now(CHINA_TZ).isoformat()}
    raw=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":"));attempt_id=hashlib.sha256(raw.encode()).hexdigest();attempt_path=Path(root)/"notification_attempts"/trade_date/stage/f"attempt-{attempt_id}.json";attempt_path.parent.mkdir(parents=True,exist_ok=True);attempt_path.write_text(raw,encoding="utf-8")
    if not accepted:raise RuntimeError("PushPlus did not return 200/ACCEPTED")
    receipt_path.parent.mkdir(parents=True,exist_ok=True);tmp=receipt_path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8");os.replace(tmp,receipt_path)
    return receipt
