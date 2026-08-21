#!/usr/bin/env python
"""Read-only project context and consistency report for humans and agents."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "docs" / "project-state.json"
V5_STATE_PATH = ROOT / "docs" / "v5-project-state.json"
REQUIRED_FILES = (
    "AGENTS.md",
    "PROJECT.md",
    "docs/project-state.json",
    "docs/ROADMAP.md",
    "docs/PROJECT_PLAN.md",
    "docs/ARCHITECTURE.md",
    "docs/MODULES.md",
    "docs/RUNBOOK.md",
    "docs/CHANGELOG.md",
    "docs/CUTOVER_PREPARATION.md",
    "docs/decisions/README.md",
)


def load_state() -> dict:
    """Legacy V4 state reader retained for migration/rollback tests."""
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))

def load_canonical_state() -> dict:
    return json.loads(V5_STATE_PATH.read_text(encoding="utf-8"))


def v3_import_violations() -> list[str]:
    violations = []
    for path in (ROOT / "v4").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from v3" in text or "import v3" in text:
            violations.append(str(path.relative_to(ROOT)))
    return violations


def runtime_observation() -> dict:
    pools=sorted((ROOT/"v5/data/morning_pools").glob("*/*.json")) if (ROOT/"v5/data/morning_pools").exists() else []
    if not pools:return {"available":False}
    pool=json.loads(pools[-1].read_text(encoding="utf-8"));trade_date=str(pool.get("trade_date",""));confirmations=sorted((ROOT/"v5/data/confirmations"/trade_date).glob("*.json")) if (ROOT/"v5/data/confirmations"/trade_date).exists() else []
    confirmation=json.loads(confirmations[-1].read_text(encoding="utf-8")) if confirmations else {}
    ownership_path=ROOT/"v5/data/ownership.json";ownership=json.loads(ownership_path.read_text(encoding="utf-8-sig")) if ownership_path.exists() else {}
    ledger_path=ROOT/"v5/data/paper/events.json";ledger=json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {"events":[]}
    buy_count=sum(row.get("event",{}).get("side")=="BUY" and row.get("event",{}).get("outcome")=="FILLED" for row in ledger.get("events",[]))
    return {
        "available": True,
        "trade_date": trade_date,
        "morning_candidates":len(pool.get("candidates",[])),
        "confirmation_candidates":len(confirmation.get("candidates",[])),
        "paper_bought":buy_count,"paper_message":"V5 single writer active" if ownership.get("paper_writer")=="v5" and ownership.get("authorized") is True else "V5 paper writer inactive",
    }

def governance_issues(state: dict) -> list[str]:
    issues=[]
    current_docs=("PROJECT.md","docs/ARCHITECTURE.md","docs/MODULES.md","docs/ROADMAP.md","docs/RUNBOOK.md","v4/README.md")
    forbidden=("python -m v4.dashboard","8898仍未改接","现有8898、生产调度","仅允许隔离离线契约开发")
    for name in current_docs:
        text=(ROOT/name).read_text(encoding="utf-8")
        for token in forbidden:
            if token in text: issues.append(f"STALE_CURRENT_DOC:{name}:{token}")
        # Common UTF-8 bytes decoded as Latin-1/CP1252. Replacement-character
        # checks alone cannot detect this reversible mojibake.
        if any(token in text for token in ("ç³»","æž¶","è¿","å€™","â†’")):
            issues.append(f"MOJIBAKE:{name}")
    if state.get("production_status")!="research_locked": issues.append("RESEARCH_GATE_CHANGED")
    return issues


def build_report() -> dict:
    state = load_canonical_state()
    missing = [name for name in REQUIRED_FILES if not (ROOT / name).exists()]
    violations = v3_import_violations()
    v3_tree_retired = not (ROOT / "v3").exists()
    governance=[]
    if state.get("production_status")!="research_locked":governance.append("RESEARCH_GATE_CHANGED")
    v5_v4_imports=[]
    for path in (ROOT/"v5").rglob("*.py"):
        text=path.read_text(encoding="utf-8")
        if "from v4" in text or "import v4" in text:v5_v4_imports.append(str(path.relative_to(ROOT)))
    if v5_v4_imports:governance.extend("V5_RUNTIME_IMPORTS_V4:"+x for x in v5_v4_imports)
    return {
        "ok": not missing and not violations and v3_tree_retired and not governance,
        "project": state.get("display_name","A股隔夜交易研究系统 V5"),
        "active_phase": state.get("active_stage"),
        "active_phase_name": "V5生产真实窗口验收",
        "production_status": state.get("production_status"),
        "dashboard": state.get("dashboard",{"url":"http://127.0.0.1:8899/"}),
        "next_tasks": state.get("next_acceptance", []),
        "known_issues": state.get("known_issues", []),
        "missing_context_files": missing,
        "v3_import_violations": violations,
        "v3_runtime_tree_retired": v3_tree_retired,
        "governance_issues": governance,
        "latest_runtime_observation": runtime_observation(),
    }


def main() -> int:
    # Windows consoles and redirected task logs do not reliably inherit UTF-8.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = build_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"{report['project']} | {report['active_phase']} {report['active_phase_name']}")
        print(f"production: {report['production_status']}")
        print(f"dashboard: {report['dashboard'].get('url')}")
        runtime = report["latest_runtime_observation"]
        if runtime.get("available"):
            print(
                "latest: {trade_date} morning={morning_candidates} "
                "confirmation={confirmation_candidates} bought={paper_bought}".format(**runtime)
            )
            print(f"paper: {runtime.get('paper_message')}")
        print("next:")
        for task in report["next_tasks"]:
            print(f"- {task}")
        print(
            f"consistency: {'PASS' if report['ok'] else 'FAIL'} "
            f"missing={len(report['missing_context_files'])} "
            f"v3_imports={len(report['v3_import_violations'])} "
            f"v3_tree_retired={report['v3_runtime_tree_retired']}"
        )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
