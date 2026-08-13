"""Read-only acceptance for one real production session.

This is deliberately separate from synthetic engineering acceptance.  It can
never manufacture a missing entity or reinterpret a failed task as success.
"""
from __future__ import annotations
from datetime import date
import json,locale,re,subprocess
from pathlib import Path
from .candidate_journal import CandidateJournal
from .task_output_contract import TaskOutputV1,audit_output_chain

REQUIRED=("morning_decision","morning_push","feature_freeze","confirmation_decision",
          "confirmation_push","paper_buy","health_check","maintenance")

def windows_time_status() -> dict:
    # Windows console utilities emit the active ANSI/OEM code page rather than
    # UTF-8 on localized hosts.  Decode explicitly and fail closed on command
    # status, while retaining replacement characters only in diagnostic text.
    encoding=locale.getpreferredencoding(False) or "utf-8"
    def run(command, timeout):
        return subprocess.run(command,capture_output=True,text=True,encoding=encoding,
                              errors="replace",timeout=timeout)
    try:
        service=run(["sc.exe","query","W32Time"],10)
        status=run(["w32tm.exe","/query","/status"],10)
        strip=run(["w32tm.exe","/stripchart","/computer:ntp.aliyun.com","/dataonly","/samples:3"],20)
    except (OSError,subprocess.SubprocessError) as exc:
        return {"passed":False,"reason":"TIME_QUERY_FAILED","detail":str(exc)}
    running=service.returncode==0 and "RUNNING" in service.stdout
    synchronized=status.returncode==0 and "Local CMOS Clock" not in status.stdout
    offsets=[]
    for value in re.findall(r"([+-])\s*(\d+(?:\.\d+)?)s",strip.stdout):
        offsets.append((-1 if value[0]=="-" else 1)*float(value[1]))
    maximum_offset=max((abs(x) for x in offsets),default=None)
    offset_ok=strip.returncode==0 and len(offsets)>=2 and maximum_offset is not None and maximum_offset<=0.5
    passed=running and synchronized and offset_ok
    return {"passed":passed,"service_running":running,"synchronized":synchronized,
            "offset_verified":offset_ok,"maximum_absolute_offset_seconds":maximum_offset,
            "service_output":service.stdout[-2000:],"status_output":status.stdout[-4000:],
            "stripchart_output":strip.stdout[-4000:],
            "reason":"OK" if passed else ("WINDOWS_TIME_OFFSET_TOO_LARGE" if running and synchronized else "WINDOWS_TIME_NOT_SYNCHRONIZED")}

def build(project_root: Path, trade_date: str) -> dict:
    day=date.fromisoformat(trade_date).isoformat(); root=Path(project_root)
    output_dir=root/"v4/data/p4/outputs"/day; outputs=[]; missing=[]; invalid=[]
    for task in REQUIRED:
        path=output_dir/f"{task}.json"
        try: outputs.append(TaskOutputV1.from_mapping(json.loads(path.read_text(encoding="utf-8"))))
        except FileNotFoundError: missing.append(task)
        except (OSError,ValueError,TypeError) as exc: invalid.append({"task":task,"error":str(exc)})
    by_name={x.task_name:x for x in outputs}; failed=[{"task":x.task_name,"status":x.status,"reason":x.reason_code} for x in outputs if x.status!="SUCCEEDED"]
    chain=CandidateJournal(root/"v4/data/candidate_journal").load(day)
    push_checks=[]
    for key,parent in ((f"v4-morning:{day}",chain.get("morning",{}).get("pool_id","")),
                       (f"v4-afternoon:{day}",chain.get("confirmation",{}).get("decision_id",""))):
        try:
            safe=__import__("hashlib").sha256(key.encode()).hexdigest()[:24]
            receipt=dict(json.loads((root/"v4/data/notifications"/f"{safe}.json").read_text(encoding="utf-8")))
            outcome=str(receipt.get("outcome","")); response=int(receipt.get("response_code",0) or 0)
            passed=(receipt.get("schema_version")=="notification-receipt-v1" and outcome=="ACCEPTED"
                    and response==200 and receipt.get("parent_entity_id")==parent
                    and bool(receipt.get("transport_request_id")))
            push_checks.append({"message_key":key,"passed":passed,"notification_id":receipt.get("notification_id",""),
                                "response_code":response,"outcome":outcome,"parent_entity_id":receipt.get("parent_entity_id","")})
        except (OSError,KeyError,ValueError,TypeError) as exc:
            push_checks.append({"message_key":key,"passed":False,"error":str(exc)})
    lineage=audit_output_chain(outputs)
    time_check=windows_time_status()
    checks={"all_tasks_present":not missing and not invalid,"all_tasks_succeeded":not failed and len(outputs)==len(REQUIRED),
            "output_lineage":lineage["passed"],"morning_entity":bool(chain.get("morning",{}).get("pool_id")),
            "confirmation_entity":bool(chain.get("confirmation",{}).get("decision_id")),
            "pushplus_200_accepted":len(push_checks)==2 and all(x.get("passed") for x in push_checks),
            "windows_time":time_check["passed"]}
    return {"schema_version":"daily-operations-acceptance-v1","trade_date":day,"passed":all(checks.values()),
            "checks":checks,"missing_tasks":missing,"invalid_tasks":invalid,"failed_tasks":failed,
            "push_checks":push_checks,"time_sync":time_check,"output_chain":lineage,"read_only":True}
