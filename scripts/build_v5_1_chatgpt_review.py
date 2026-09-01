"""Build a read-only, secret-free V5.1 source review bundle."""
from __future__ import annotations

import csv
import hashlib
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
STAGE = ROOT / f".v51_review_stage_{STAMP}"
ZIP_PATH = ROOT / "V5_1_CHATGPT_REVIEW_2026-09-01.zip"

DOCS = [
    "docs/V5_1_ARCHITECTURE.md", "docs/V5_1_MIGRATION_ACCEPTANCE.md",
    "docs/V5_1_RUNBOOK.md", "docs/V5_1_PRODUCTION_CUTOVER.md",
    "docs/V5_1_ACCEPTANCE_CONTRACT.md", "docs/V5_1_RELEASE_PROCESS.md",
    "docs/V5_1_SHADOW_TASK_MANIFEST.md", "docs/project-state.json",
    "docs/ROADMAP.md", "docs/MODULES.md", "docs/CHANGELOG.md",
    "docs/V5_PRODUCT_CHARTER.md",
]
SHARED = [
    "pytest.ini", "requirements-v5_1.lock", "scripts/project_status.py", "scripts/audit_production_tasks.ps1",
    "scripts/build_v5_1_release.py",
    "v5/calendar.py", "v5/data_production.py", "v5/market_snapshot.py",
    "v5/paper.py", "v5/order_quantity.py", "v5/independence_audit.py",
]

def copy(relative: str) -> None:
    source = ROOT / relative
    if not source.exists():
        return
    target = STAGE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

def run(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8",
                               errors="replace", stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, check=False)
    return completed.returncode, completed.stdout

def main() -> int:
    STAGE.mkdir(parents=True)
    for path in sorted((ROOT / "v5_1").rglob("*")):
        if not path.is_file() or any(part in {"data", "shadow_data", "replay", "test_data", "__pycache__", "logs", "cache"} for part in path.parts):
            continue
        if path.suffix in {".pyc", ".env"} or "token" in path.name.lower() or "secret" in path.name.lower():
            continue
        copy(path.relative_to(ROOT).as_posix())
    for path in sorted((ROOT / "shared_core").rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix==".pyc":
            continue
        copy(path.relative_to(ROOT).as_posix())
    for path in sorted((ROOT / "tests").glob("test_v5_1_*.py")):
        copy(path.relative_to(ROOT).as_posix())
    # Shared V5 tests are included because V5.1 reuses the conservative
    # execution-book contract implemented at this boundary.
    copy("tests/test_v5_data_and_funnel.py")
    for relative in DOCS + SHARED:
        copy(relative)

    git_commands = [
        ["git", "status", "--short"], ["git", "log", "-15", "--oneline"],
        ["git", "diff", "--stat"],
        ["git", "diff", "--", "v5_1", *DOCS[:5], *SHARED],
    ]
    git_text = []
    for command in git_commands:
        code, output = run(command); git_text.append(f"> {' '.join(command)}\nexit_code={code}\n{output}")
    (STAGE / "GIT_REVIEW_STATE.txt").write_text("\n".join(git_text), encoding="utf-8")

    py = str(ROOT / ".venv" / "Scripts" / "python.exe")
    test_files = [str(path) for path in sorted((ROOT / "tests").glob("test_v5_1_*.py"))]
    commands = [
        [py, "-m", "pytest", "-q", *test_files],
        [py, "-m", "pytest", "-q"],
        [py, "scripts/project_status.py"],
        [py, "-m", "v5.independence_audit"],
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts/audit_production_tasks.ps1")],
        [py, "-m", "pytest", "-q", "tests/test_v5_1_runtime_orchestration.py"],
        [py, "-m", "pytest", "-q", "tests/test_v5_1_dashboard_comparison.py"],
        [py, "-m", "pytest", "-q", "tests/test_v5_1_notifications_runtime.py"],
        [py, "-m", "pytest", "-q", "tests/test_v5_data_and_funnel.py"],
        ["git", "diff", "--check"],
    ]
    results=[];failed=[]
    for command in commands:
        code,output=run(command);results.append(f"> {' '.join(command)}\nexit_code={code}\n{output}")
        if code:failed.append(" ".join(command))
    (STAGE / "V5_1_TEST_AND_AUDIT_RESULTS.txt").write_text("\n".join(results),encoding="utf-8")

    direct_v5_imports=[]
    for path in sorted((ROOT / "v5_1").glob("*.py")):
        for number,line in enumerate(path.read_text(encoding="utf-8").splitlines(),1):
            if line.startswith("from v5.") or line.startswith("import v5."):
                direct_v5_imports.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line}")
    manifest=f"""# V5.1 ChatGPT Review Manifest

Generated: {datetime.now().astimezone().isoformat()}

## Scope

- Complete `v5_1/` source, excluding runtime data/cache/logs/secrets.
- All `tests/test_v5_1_*.py` tests.
- `tests/test_v5_data_and_funnel.py`, because V5.1 uses the shared V5 dual-source conservative execution-book contract.
- Complete canonical `shared_core/`, release builder/config/lock, V5.1 authority documents and narrowly scoped compatibility/audit boundaries.
- G1 files are not included and were not modified by this packaging operation.
- Stable runtime primitives are canonical in `shared_core`; included V5 files are compatibility aliases/audit boundaries, not V5.1 runtime dependencies.

## Runtime and ownership truth

- Actual V5.1 entrypoint: `python -m v5_1.task_runner <task>`.
- V5.1 Windows Scheduler tasks: not registered.
- Formal 09:35 task: not registered. Existing V5 09:25 tasks remain.
- Duplicate V5/V5.1 business writers: no; V5.1 has no scheduled production writer.
- Production owner: V5.
- Dashboard 8899: V5 and unchanged. V5.1 preview remains separate.
- `research_locked=true`; `broker_orders=false`; `production_cutover_authorized=false`.
- V5.1 status: OFFLINE RELEASE ACCEPTANCE PASS; ZERO DIRECT V5 RUNTIME IMPORTS; REAL-WINDOW ACCEPTANCE PENDING; CUTOVER READY NO.
- Strategy effectiveness: UNPROVEN.

## Required answers

1. Persistent Master removes normal dependence on rediscovering all securities each morning. SSE/SZSE form the authoritative base and Eastmoney is an optional third-party check; production remains fail-closed until a fresh allowed verification cycle exists.
2. Daily Tradability is a separate fact derived from Master plus same-day per-symbol Daily Status.
3. Freshness is fixed by the exchange calendar: current open session or previous completed open session; callers cannot expand it.
4. 09:35 replaces 09:25 only inside V5.1. Production remains V5 and still uses its registered 09:25 tasks.
5. V5.1 source/dashboard formal flow uses 09:35; legacy V5 documentation/tasks may truthfully mention 09:25.
6. Decision and execution snapshots are physically and contractually distinct.
7. 14:50:40 execution reacquires a fresh dual-source executable book.
8. Next-open SELL uses a fresh `sell_execution` snapshot and conservative bid, never an after-the-fact official open.
9. CloseScan does not read Morning Pool.
10. CloseScan owns independent candidate, selection, run, paper and comparison facts.
11. Baseline and CloseScan share read-only market acquisition when appropriate but use isolated facts and ledgers.
12. V5 legacy and V5.1 evidence roots/cohorts are separate.
13. G1 is absent from the V5.1 dashboard.
14. The five dashboard pages show only V5.1 Baseline and CloseScan.
15. Existing 2026-08-26/27 failure history was not modified or backfilled.
16. Existing 2026-08-24/25 V5 history was not modified; V5.1 has no rewritten history.
17. Windows Scheduler was not modified; proposed 09:35 tasks remain unregistered.
18. No unauthorized second business writer exists.
19. Pending real windows: official independent Master, 09:30 observation, 09:35 pool, 14:49 freeze, 14:50 confirmation/execution, D preliminary acceptance, next-open 09:30 exit and RoundTripAcceptance.
20. `research_locked=true`; `broker_orders=false`.

## Verification result

All bundle commands passed: {str(not failed).lower()}.
Failed commands: {failed or 'none'}.
Offline command success does not satisfy cutover because V5.1 has zero accepted natural strict round-trip days and Scheduler/single-writer/rollback/cutover gates remain pending.

### Direct V5 runtime imports

```text
{chr(10).join(direct_v5_imports) or 'none'}
```

## Final cutover gate

- Offline tests: PASS if commands above exit 0.
- Security Master raw-response/match/verification evidence: implemented; natural-window acceptance pending.
- V5.1 source independence: PASS when the direct-import list above is empty; production ownership migration remains separately pending.
- V5.1 real-window strict acceptance: PENDING (0 complete days).
- Replace 8899 now: **NO**.
- Strategy effectiveness: **UNPROVEN**.

The bundle is an engineering review artifact, not evidence of profitability or production correctness.
"""
    (STAGE / "V5_1_REVIEW_MANIFEST.md").write_text(manifest,encoding="utf-8")

    rows=[]
    for path in sorted(p for p in STAGE.rglob("*") if p.is_file()):
        rows.append((path.relative_to(STAGE).as_posix(),hashlib.sha256(path.read_bytes()).hexdigest()))
    with (STAGE / "MANIFEST_SHA256.csv").open("w",encoding="utf-8",newline="") as handle:
        writer=csv.writer(handle);writer.writerow(["path","sha256"]);writer.writerows(rows)
    if ZIP_PATH.exists():ZIP_PATH.unlink()
    with ZipFile(ZIP_PATH,"w",ZIP_DEFLATED) as archive:
        for path in sorted(p for p in STAGE.rglob("*") if p.is_file()):archive.write(path,path.relative_to(STAGE))
    print(ZIP_PATH)
    print(f"files={sum(1 for p in STAGE.rglob('*') if p.is_file())} sha256={hashlib.sha256(ZIP_PATH.read_bytes()).hexdigest()}")
    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(main())
