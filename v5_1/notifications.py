"""V5.1 notification ownership; disabled until atomic cutover authorization."""
from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
import json,os
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from shared_core.core import ContractViolation
from .facts import content_id,save_immutable
from . import SYSTEM_VERSION,CONTRACT_VERSION

@dataclass(frozen=True)
class NotificationReceiptV51:
    trade_date:str;stage:str;entity_id:str;payload_hash:str;http_status:int;provider_code:int;accepted:bool;recorded_at:str;system_version:str=SYSTEM_VERSION;contract_version:str=CONTRACT_VERSION;schema_version:str="v5.1-notification-receipt-v1"
    @property
    def receipt_id(self):return content_id("v51notify1",asdict(self))
    def to_dict(self):return {**asdict(self),"receipt_id":self.receipt_id}

class V51NotificationService:
    def __init__(self,root,ownership_file,token=None,transport=None):self.root=Path(root);self.ownership_file=Path(ownership_file);self.token=token;self.transport=transport
    def _authorized(self):
        try:row=json.loads(self.ownership_file.read_text(encoding="utf-8"))
        except (OSError,ValueError):return False
        return row.get("production_owner")=="v5.1" and row.get("notifications_owner")=="v5.1" and row.get("authorized") is True
    def send(self,*,trade_date,stage,entity_id,title,content,recorded_at):
        if not self._authorized():raise ContractViolation("V5.1 notification ownership not authorized")
        token=self.token or os.getenv("PUSHPLUS_TOKEN")
        if not token:raise ContractViolation("PushPlus token missing")
        payload={"token":token,"title":title,"content":content,"template":"html"};raw=urlencode(payload).encode();request=Request("https://www.pushplus.plus/send",data=raw,method="POST")
        if self.transport is None:
            with urlopen(request,timeout=15) as response:status=response.status;body=json.loads(response.read().decode("utf-8"))
        else:status,body=self.transport(request)
        semantic=str(body.get("msg",body.get("message",""))).strip().lower()
        accepted=status==200 and int(body.get("code",-1))==200 and semantic in {"accepted","success","请求成功","发送成功"}
        receipt=NotificationReceiptV51(trade_date,stage,entity_id,content_id("payload",{"title":title,"content":content}),status,int(body.get("code",-1)),accepted,recorded_at);save_immutable(self.root/"notification_receipts"/trade_date/f"{receipt.receipt_id}.json",receipt.to_dict())
        if not accepted:raise ContractViolation("PushPlus not HTTP 200/ACCEPTED")
        return receipt
