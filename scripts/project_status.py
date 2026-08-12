#!/usr/bin/env python
"""Read-only project context and consistency report for humans and agents."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "docs" / "project-state.json"
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
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def v3_import_violations() -> list[str]:
    violations = []
    for path in (ROOT / "v4").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from v3" in text or "import v3" in text:
            violations.append(str(path.relative_to(ROOT)))
    return violations


def runtime_observation() -> dict:
    journal_dir = ROOT / "v4" / "data" / "candidate_journal"
    execution_dir = ROOT / "v4" / "data" / "p3" / "execution_batches"
    journals = sorted(journal_dir.glob("*.json")) if journal_dir.exists() else []
    if not journals:
        return {"available": False}
    journal = json.loads(journals[-1].read_text(encoding="utf-8"))
    trade_date = str(journal.get("trade_date", ""))
    buy_path = execution_dir / trade_date / "buy.json"
    buy = json.loads(buy_path.read_text(encoding="utf-8")) if buy_path.exists() else {}
    return {
        "available": True,
        "trade_date": trade_date,
        "morning_candidates": len(journal.get("morning", {}).get("candidates", [])),
        "confirmation_candidates": len(
            journal.get("confirmation", {}).get("candidates", [])
        ),
        "paper_bought": int(buy.get("result", {}).get("filled", 0) or 0),
        "paper_message": ("filled" if buy.get("result", {}).get("filled") else
                          "empty_or_blocked" if buy else "no batch"),
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
    state = load_state()
    missing = [name for name in REQUIRED_FILES if not (ROOT / name).exists()]
    violations = v3_import_violations()
    v3_tree_retired = not (ROOT / "v3").exists()
    governance=governance_issues(state)
    return {
        "ok": not missing and not violations and v3_tree_retired and not governance,
        "project": state.get("display_name"),
        "active_phase": state.get("active_phase"),
        "active_phase_name": state.get("active_phase_name"),
        "production_status": state.get("production_status"),
        "dashboard": state.get("dashboard"),
        "next_tasks": state.get("next_tasks", []),
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
