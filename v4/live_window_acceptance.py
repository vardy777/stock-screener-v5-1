"""Read-only acceptance of one real 09:25 -> next-session 09:30 evidence chain."""

from __future__ import annotations

from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path

from phase1.overnight.capture_health import evaluate_capture_session
from .candidate_journal import CandidateJournal
from .p2_acceptance import validate_p2_session


WINDOWS = ("morning_0925", "feature_1449", "confirmation_1450", "sell_0930")


def _hash(value) -> str:
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read(path: Path) -> tuple[dict,str]:
    try:
        raw=path.read_bytes(); value=json.loads(raw.decode("utf-8"))
        return (value if isinstance(value,dict) else {}),hashlib.sha256(raw).hexdigest()
    except (OSError,UnicodeError,ValueError,TypeError): return {},""


def validate_live_window_chain(trade_date: str, evidence_dir: Path) -> dict:
    day=date.fromisoformat(trade_date).isoformat(); root=Path(evidence_dir); checks=[]; artifacts=[]; values={}
    for name in WINDOWS:
        path=root/day/f"{name}.json"; value,digest=_read(path); values[name]=value
        artifacts.append({"window":name,"path":str(path),"sha256":digest,"present":bool(value)})
        reasons=[]
        if not value: reasons.append("EVIDENCE_MISSING_OR_INVALID")
        if value.get("schema_version") != "live-window-evidence-v1": reasons.append("SCHEMA_INVALID")
        if value.get("status") != "PASSED": reasons.append("WINDOW_NOT_PASSED")
        if name == "sell_0930":
            if value.get("source_trade_date") != day or value.get("trade_date") == day:
                reasons.append("NEXT_SESSION_DATE_MISMATCH")
        elif value.get("trade_date") != day: reasons.append("TRADE_DATE_MISMATCH")
        stamp=value.get("observed_at","")
        try:
            parsed=datetime.fromisoformat(stamp)
            if parsed.tzinfo is None or parsed.utcoffset() is None: raise ValueError
        except (TypeError,ValueError): reasons.append("OBSERVED_AT_INVALID")
        if not str(value.get("snapshot_id","")).startswith("ms1-"): reasons.append("SNAPSHOT_ID_MISSING")
        if float(value.get("fresh_quote_coverage",0) or 0) < .95: reasons.append("COVERAGE_BELOW_95_PERCENT")
        checks.append({"window":name,"passed":not reasons,"reasons":reasons})
    morning=values["morning_0925"]; feature=values["feature_1449"]; confirm=values["confirmation_1450"]; sell=values["sell_0930"]
    lineage=[]
    def relation(name, passed, detail): lineage.append({"name":name,"passed":bool(passed),"detail":detail})
    relation("morning_entity",str(morning.get("pool_id","")).startswith("mp-"),morning.get("pool_id",""))
    relation("feature_context",str(feature.get("feature_context_id","")).startswith("fc1-"),feature.get("feature_context_id",""))
    relation("confirmation_entity",str(confirm.get("decision_id","")).startswith("cd-"),confirm.get("decision_id",""))
    relation("confirmation_to_morning",confirm.get("morning_pool_id") == morning.get("pool_id") and bool(morning.get("pool_id")),confirm.get("morning_pool_id",""))
    relation("confirmation_to_feature",confirm.get("feature_context_id") == feature.get("feature_context_id") and bool(feature.get("feature_context_id")),confirm.get("feature_context_id",""))
    relation("candidate_subset",set(confirm.get("candidate_codes",[])).issubset(set(morning.get("candidate_codes",[]))),"subset")
    relation("next_session_sell",sell.get("source_trade_date") == day and sell.get("trade_date") != day,sell.get("trade_date",""))
    relation("cohort_separation",all(x.get("strict_cohort_separated") is True for x in values.values()),"strict/paper separated")
    body={"schema_version":"live-window-acceptance-v1","trade_date":day,"checks":checks,"lineage":lineage,
          "artifacts":artifacts,"production_mutated":False}
    return {**body,"passed":all(x["passed"] for x in checks+lineage),"acceptance_id":"lwa1-"+_hash(body)[:24]}


def write_acceptance_report(report: dict, output: Path) -> Path:
    """Write only an explicitly supplied report destination, never source evidence."""
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_suffix(output.suffix+".tmp")
    temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    temporary.replace(output); return output


def write_evidence_once(value: dict, path: Path) -> Path:
    """Create immutable evidence once; an identical retry is idempotent."""
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)
    try:
        with path.open("x",encoding="utf-8") as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
    except FileExistsError:
        if path.read_text(encoding="utf-8") != raw: raise ValueError(f"evidence is immutable: {path}")
    return path


def derive_project_evidence(trade_date: str, next_session_date: str, *, journal_dir: Path,
                            log_dir: Path, snapshot_root: Path) -> dict[str,dict]:
    """Project existing immutable artifacts into evidence records without writing them."""
    day=date.fromisoformat(trade_date).isoformat(); next_day=date.fromisoformat(next_session_date).isoformat()
    chain=CandidateJournal(journal_dir).load(day); morning=dict(chain.get("morning",{}) or {}); confirm=dict(chain.get("confirmation",{}) or {})
    p2=validate_p2_session(day,journal_dir=journal_dir,log_dir=log_dir)
    signal=evaluate_capture_session(snapshot_root,"signal",day); buy=evaluate_capture_session(snapshot_root,"buy",day)
    sell=evaluate_capture_session(snapshot_root,"sell",next_day)
    strict_root=Path(snapshot_root)/"strict"; separated=strict_root.is_dir() and (Path(snapshot_root)/"paper_only").is_dir()
    def coverage(entity):
        state=dict(entity.get("market_state",{}) or {}); return float(state.get("fresh_quote_coverage",state.get("quote_coverage",0)) or 0)
    def observed(entity,key): return entity.get(key,"")
    def capture_manifest(result,session):
        name=result.get("best",{}).get("manifest","")
        roots=[Path(snapshot_root)/"strict"/session,Path(snapshot_root)/session]
        return next((_read(path/name)[0] for path in roots if name and (path/name).is_file()),{})
    signal_meta=capture_manifest(signal,"signal"); buy_meta=capture_manifest(buy,"buy"); sell_meta=capture_manifest(sell,"sell")
    morning_lineage=dict(morning.get("lineage",{}) or {}); confirm_lineage=dict(confirm.get("lineage",{}) or {})
    contexts={str(x.get("input_context_id","")) for x in confirm.get("candidates",[]) if x.get("input_context_id")}
    context_id=next(iter(contexts),"") if len(contexts)==1 else ""
    return {
        "morning_0925":{"schema_version":"live-window-evidence-v1","status":"PASSED" if p2["checks"].get("morning_schema_v1") and p2["checks"].get("morning_push_same_id") else "FAILED",
            "trade_date":day,"observed_at":observed(morning,"captured_at"),"snapshot_id":morning_lineage.get("input_snapshot_id",""),
            "fresh_quote_coverage":coverage(morning),"strict_cohort_separated":separated,"pool_id":morning.get("pool_id",""),"candidate_codes":morning.get("candidate_codes",[])},
        "feature_1449":{"schema_version":"live-window-evidence-v1","status":"PASSED" if signal.get("passed") and context_id.startswith("fc1-") else "FAILED",
            "trade_date":day,"observed_at":signal_meta.get("captured_at",""),
            "snapshot_id":signal_meta.get("snapshot_id",signal_meta.get("input_snapshot_id","")),"fresh_quote_coverage":signal.get("best",{}).get("coverage",0),
            "strict_cohort_separated":separated,"feature_context_id":context_id,"capture":signal},
        "confirmation_1450":{"schema_version":"live-window-evidence-v1","status":"PASSED" if p2.get("passed") and buy.get("passed") else "FAILED",
            "trade_date":day,"observed_at":observed(confirm,"decided_at"),"snapshot_id":confirm_lineage.get("input_snapshot_id",""),
            "fresh_quote_coverage":min(coverage(confirm),float(buy.get("best",{}).get("coverage",0) or 0)),"strict_cohort_separated":separated,
            "decision_id":confirm.get("decision_id",""),"morning_pool_id":confirm.get("morning_pool_id",""),"feature_context_id":context_id,
            "candidate_codes":confirm.get("candidate_codes",[]),"capture":buy},
        "sell_0930":{"schema_version":"live-window-evidence-v1","status":"PASSED" if sell.get("passed") else "FAILED",
            "trade_date":next_day,"source_trade_date":day,"observed_at":sell_meta.get("captured_at",""),
            "snapshot_id":sell_meta.get("snapshot_id",sell_meta.get("input_snapshot_id","")),"fresh_quote_coverage":sell.get("best",{}).get("coverage",0),
            "strict_cohort_separated":separated,"capture":sell},
    }
