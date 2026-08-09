"""Pure state-machine rehearsal for the complete overnight lifecycle."""

from __future__ import annotations

import hashlib,json


ORDER=("MORNING_RECORDED","MORNING_NOTIFIED","FEATURE_FROZEN","CONFIRMATION_RECORDED",
       "CONFIRMATION_NOTIFIED","BUY_TERMINAL","SELL_TERMINAL","DASHBOARD_PROJECTED")


def rehearse(events: list[dict]) -> dict:
    reasons=[]; seen=[]; terminal={}
    for index,event in enumerate(events):
        name=event.get("event",""); status=event.get("status","")
        if name not in ORDER: reasons.append(f"UNKNOWN_EVENT:{index}"); continue
        expected=ORDER[len(seen)] if len(seen)<len(ORDER) else ""
        if name!=expected: reasons.append(f"ORDER_VIOLATION:{expected}->{name}"); continue
        if status not in {"SUCCEEDED","EMPTY","BLOCKED","FAILED","OUTCOME_UNKNOWN","DEFERRED"}:
            reasons.append(f"INVALID_STATUS:{name}"); continue
        if name in terminal: reasons.append(f"DUPLICATE_TERMINAL:{name}"); continue
        if name in {"MORNING_NOTIFIED","CONFIRMATION_NOTIFIED"} and status in {"FAILED","OUTCOME_UNKNOWN"}:
            reasons.append(f"NOTIFICATION_NOT_CONFIRMED:{name}")
        if name=="BUY_TERMINAL" and status=="OUTCOME_UNKNOWN": reasons.append("BUY_REQUIRES_RECOVERY")
        if name=="SELL_TERMINAL" and status in {"FAILED","OUTCOME_UNKNOWN"}: reasons.append("SELL_REQUIRES_RECOVERY")
        seen.append(name); terminal[name]=status
    if seen!=list(ORDER): reasons.append("INCOMPLETE_LIFECYCLE")
    body={"schema_version":"offline-lifecycle-rehearsal-v1","events":events,"seen":seen,"reasons":reasons,
          "writes_production":False,"network_called":False}
    raw=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return {**body,"passed":not reasons,"rehearsal_id":"rehearsal1-"+hashlib.sha256(raw.encode()).hexdigest()[:24]}


def successful_empty_cycle():
    return rehearse([{"event":name,"status":"EMPTY" if name in {"BUY_TERMINAL","SELL_TERMINAL"} else "SUCCEEDED"} for name in ORDER])
