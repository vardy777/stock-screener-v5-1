"""Immutable V5 operational failure alerts, separate from business notifications."""
from __future__ import annotations
from datetime import datetime
import hashlib,json,os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .core import CHINA_TZ,ContractViolation
from .notification import _token

def send_failure(root,trade_date,task,error,env_path,*,transport=None):
    root=Path(root);token=_token(env_path);safe_error=str(error).replace(token,"[REDACTED]")[:1000]
    message=f"V5任务失败：{task}\n交易日：{trade_date}\n原因：{safe_error}\n系统已停止该环节，不会使用旧数据补跑；research_locked 保持启用。"
    fingerprint=hashlib.sha256(f"{trade_date}|{task}|{safe_error}".encode()).hexdigest()
    receipt_path=root/"alerts"/trade_date/f"{task}-{fingerprint[:16]}.json"
    if receipt_path.exists():
        prior=json.loads(receipt_path.read_text(encoding="utf-8"))
        if prior.get("outcome")=="ACCEPTED":return prior
        raise ContractViolation("V5 alert immutable collision")
    post=urlencode({"token":token,"title":f"V5系统故障：{task}","content":message,"template":"txt"}).encode()
    transport=transport or (lambda:json.loads(urlopen(Request("https://www.pushplus.plus/send",data=post,headers={"Content-Type":"application/x-www-form-urlencoded"}),timeout=15).read().decode()))
    response=transport();accepted=response.get("code")==200
    receipt={"schema_version":"v5-operational-alert-v1","trade_date":trade_date,"task":task,"error":safe_error,"fingerprint":fingerprint,"outcome":"ACCEPTED" if accepted else "REJECTED","response_code":response.get("code"),"recorded_at":datetime.now(CHINA_TZ).isoformat()}
    raw=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":"));attempt_id=hashlib.sha256(raw.encode()).hexdigest();attempt=root/"alert_attempts"/trade_date/task/f"{fingerprint}-{attempt_id[:16]}.json";attempt.parent.mkdir(parents=True,exist_ok=True);tmp_attempt=attempt.with_suffix(f".{os.getpid()}.tmp");tmp_attempt.write_text(raw,encoding="utf-8")
    try:os.link(tmp_attempt,attempt)
    finally:tmp_attempt.unlink(missing_ok=True)
    if not accepted:raise RuntimeError("PushPlus alert did not return 200/ACCEPTED")
    receipt_path.parent.mkdir(parents=True,exist_ok=True);tmp=receipt_path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8");os.replace(tmp,receipt_path);return receipt
