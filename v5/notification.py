"""V5-only PushPlus projection from final V5 facts; never recalculates candidates."""
from __future__ import annotations
from datetime import datetime
import hashlib,html,json,os,msvcrt,time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .core import CHINA_TZ,ContractViolation
from .fact_reader import latest
from .market_state import MarketStateV1

MAXIMUM_NOTIFICATION_QUOTE_AGE_SECONDS=120

def _validate_snapshot_freshness(root,trade_date,snapshot_id,as_of):
    if as_of is None:return None
    if as_of.tzinfo is None or as_of.utcoffset() is None:raise ContractViolation("V5 notification as_of timezone required")
    path=Path(root)/"snapshots"/trade_date/f"{snapshot_id}.json"
    if not path.exists():raise ContractViolation("V5 notification snapshot content missing")
    raw=json.loads(path.read_text(encoding="utf-8"));quotes=raw.get("quotes",[])
    if not quotes:raise ContractViolation("V5 notification snapshot quotes missing")
    times=[datetime.fromisoformat(str(row.get("exchange_time"))) for row in quotes]
    if any(value.tzinfo is None or value.utcoffset() is None for value in times):raise ContractViolation("V5 notification quote time invalid")
    maximum=max((as_of.astimezone(CHINA_TZ)-value.astimezone(CHINA_TZ)).total_seconds() for value in times)
    if maximum<0 or maximum>MAXIMUM_NOTIFICATION_QUOTE_AGE_SECONDS:raise ContractViolation("V5 notification snapshot stale")
    return maximum

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
    maximum_quote_age=_validate_snapshot_freshness(root,trade_date,entity.get("snapshot_id",""),as_of)
    market_path=Path(root)/"market_states"/trade_date/f"{entity.get('market_state_id','')}.json"
    if not market_path.exists():raise ContractViolation("V5 notification market state missing")
    market=MarketStateV1.from_mapping(json.loads(market_path.read_text(encoding="utf-8"))).to_dict()
    if market["snapshot_id"]!=entity.get("snapshot_id"):raise ContractViolation("V5 notification market state snapshot mismatch")
    candidates=entity.get("candidates",[]);rows=[]
    for row in candidates:
        entry=(f"冻结卖一参考 ¥{float(row['ask1']):.2f}；仅按14:50窗口本地模拟" if stage=="confirmation" and row.get("ask1") else "早盘观察，不展示买价")
        rows.append(f"<li><b>{html.escape(row['name'])} {row['code']}</b> · 排名#{row['rank']} · 涨幅{float(row['change_pct']):.2f}%<br><b>理由：</b>{html.escape('；'.join(row.get('reasons',[])))}<br><b>风险：</b>{html.escape('；'.join(row.get('risks',[])))}<br><b>执行：</b>{html.escape(entry)}；下一交易日09:30后按买一和滑点模拟卖出，当前不预测卖价</li>")
    market_summary=f"市场：{market['regime']}；上涨{market['advancers']} / 下跌{market['decliners']}；上涨占比{float(market['advance_ratio'])*100:.1f}%；成交额{float(market['total_amount'])/1e8:.1f}亿元；中位涨幅{float(market['median_change'])*100:.2f}%"
    content=f"<h3>{title}</h3><p><b>今日结论：</b>{html.escape(action)}<br>{html.escape(market_summary)}<br>V5实体：{parent}<br>行情快照：{entity.get('snapshot_id','')}<br>研究状态：research_locked</p>"+(f"<ol>{''.join(rows)}</ol>" if rows else "<p>当前没有推荐股票。空仓是有效决策，不使用残缺行情或旧候选凑数。</p>")+"<p>排序分不是上涨概率；仅用于本地模拟研究，不连接券商。</p>"
    payload={"title":title,"content":content,"template":"html","parent_entity_id":parent,"snapshot_id":entity.get("snapshot_id",""),"market_state_id":entity.get("market_state_id",""),"maximum_quote_age_seconds":maximum_quote_age,"candidate_codes":[str(row["code"]) for row in candidates],"candidate_count":len(candidates),"stage":stage,"trade_date":trade_date};payload["payload_sha256"]=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest();return payload
def _token(env_path):
    for line in Path(env_path).read_text(encoding="utf-8").splitlines():
        if line.startswith("PUSHPLUS_TOKEN="):return line.split("=",1)[1].strip()
    raise ContractViolation("PushPlus token missing")
def send(root,trade_date,stage,env_path,transport=None,*,as_of=None):
    root=Path(root);payload=build_payload(root,trade_date,stage,as_of=as_of);receipt_path=root/"notifications"/trade_date/f"{stage}.json";lock_path=root/"notification_locks"/trade_date/f"{stage}.lock";lock_path.parent.mkdir(parents=True,exist_ok=True)
    with lock_path.open("a+b") as lock:
        deadline=time.monotonic()+20
        while True:
            try:lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);break
            except OSError:
                if time.monotonic()>=deadline:raise ContractViolation("V5 notification lock timeout")
                time.sleep(.02)
        try:
            if receipt_path.exists():
                prior=json.loads(receipt_path.read_text(encoding="utf-8"))
                if prior.get("outcome")=="ACCEPTED" and prior.get("payload_sha256")==payload["payload_sha256"]:return prior
                raise ContractViolation("V5 notification immutable collision")
            token=_token(env_path);post=urlencode({"token":token,"title":payload["title"],"content":payload["content"],"template":"html"}).encode();transport=transport or (lambda:json.loads(urlopen(Request("https://www.pushplus.plus/send",data=post,headers={"Content-Type":"application/x-www-form-urlencoded"}),timeout=15).read().decode()))
            response=transport();accepted=response.get("code")==200;receipt={"schema_version":"v5-notification-receipt-v1","parent_entity_id":payload["parent_entity_id"],"payload_sha256":payload["payload_sha256"],"stage":stage,"trade_date":trade_date,"outcome":"ACCEPTED" if accepted else "REJECTED","response_code":response.get("code"),"recorded_at":datetime.now(CHINA_TZ).isoformat()};raw=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":"));attempt_id=hashlib.sha256(raw.encode()).hexdigest();attempt_path=root/"notification_attempts"/trade_date/stage/f"attempt-{attempt_id}.json";attempt_path.parent.mkdir(parents=True,exist_ok=True);tmp_attempt=attempt_path.with_suffix(f".{os.getpid()}.tmp");tmp_attempt.write_text(raw,encoding="utf-8")
            try:os.link(tmp_attempt,attempt_path)
            finally:tmp_attempt.unlink(missing_ok=True)
            if not accepted:raise RuntimeError("PushPlus did not return 200/ACCEPTED")
            receipt_path.parent.mkdir(parents=True,exist_ok=True);tmp=receipt_path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
            try:os.link(tmp,receipt_path)
            finally:tmp.unlink(missing_ok=True)
            return receipt
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
