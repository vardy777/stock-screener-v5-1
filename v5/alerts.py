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
    root=Path(root);message=f"V5任务失败：{task}\n交易日：{trade_date}\n原因：{error}\n系统已停止该环节，不会使用旧数据补跑；research_locked 保持启用。"
    fingerprint=hashlib.sha256(f"{trade_date}|{task}|{error}".encode()).hexdigest()
    receipt_path=root/"alerts"/trade_date/f"{task}-{fingerprint[:16]}.json"
    if receipt_path.exists():
        prior=json.loads(receipt_path.read_text(encoding="utf-8"))
        if prior.get("outcome")=="ACCEPTED":return prior
        raise ContractViolation("V5 alert immutable collision")
    token=_token(env_path);post=urlencode({"token":token,"title":f"V5系统故障：{task}","content":message,"template":"txt"}).encode()
    transport=transport or (lambda:json.loads(urlopen(Request("https://www.pushplus.plus/send",data=post,headers={"Content-Type":"application/x-www-form-urlencoded"}),timeout=15).read().decode()))
    response=transport();accepted=response.get("code")==200
    receipt={"schema_version":"v5-operational-alert-v1","trade_date":trade_date,"task":task,"error":error,"fingerprint":fingerprint,"outcome":"ACCEPTED" if accepted else "REJECTED","response_code":response.get("code"),"recorded_at":datetime.now(CHINA_TZ).isoformat()}
    raw=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":"));attempt=root/"alert_attempts"/trade_date/task/f"{fingerprint}.json";attempt.parent.mkdir(parents=True,exist_ok=True);attempt.write_text(raw,encoding="utf-8")
    if not accepted:raise RuntimeError("PushPlus alert did not return 200/ACCEPTED")
    receipt_path.parent.mkdir(parents=True,exist_ok=True);tmp=receipt_path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8");os.replace(tmp,receipt_path);return receipt
