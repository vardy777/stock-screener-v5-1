"""Build a secret-free ChatGPT review package for the exact frozen V5.1-RC1."""
from __future__ import annotations
import csv,hashlib,json,os,shutil,subprocess,tempfile,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RC=ROOT/"V5_1_RC1.zip"
OUT=ROOT/"V5_1_RC1_CHATGPT_REVIEW_2026-09-01.zip"
RC_COMMIT="14cbcf2615a68a50789997e26527f82074a2ca6e"
SCOPE=["shared_core","v5_1","requirements-v5_1.lock","scripts/build_v5_1_release.py","docs/V5_1_ARCHITECTURE.md","docs/V5_1_MIGRATION_ACCEPTANCE.md","docs/V5_1_RUNBOOK.md","docs/V5_1_PRODUCTION_CUTOVER.md","docs/V5_1_SHADOW_TASK_MANIFEST.md","docs/V5_1_ACCEPTANCE_CONTRACT.md","docs/V5_1_RELEASE_PROCESS.md","docs/project-state.json","docs/CHANGELOG.md"]

def run(command,cwd=ROOT,env=None):
    result=subprocess.run(command,cwd=cwd,env=env,text=True,encoding="utf-8",errors="replace",stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    return result.returncode,result.stdout
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    if not RC.exists():raise SystemExit("V5_1_RC1.zip missing")
    with tempfile.TemporaryDirectory() as tmp:
        stage=Path(tmp)/"review";release=stage/"release";release.mkdir(parents=True)
        shutil.copy2(RC,stage/RC.name)
        with zipfile.ZipFile(RC) as archive:archive.extractall(release)
        for name in ("docs/project-state.json","docs/CHANGELOG.md"):
            source=ROOT/name;target=stage/"post_freeze_evidence"/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        manifest=json.loads((release/"RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
        commands=[
            ["git","show","--stat","--oneline",RC_COMMIT],
            ["git","show","--format=fuller","--no-patch",RC_COMMIT],
            ["git","diff",f"{RC_COMMIT}^",RC_COMMIT,"--",*SCOPE],
            ["git","status","--short","--",*SCOPE],
            ["git","status","--short"],
            ["git","log","-5","--oneline"],
        ]
        git_results=[]
        for command in commands:
            code,out=run(command);git_results.append(f"> {' '.join(command)}\nexit_code={code}\n{out}")
        (stage/"GIT_RC1_EVIDENCE.txt").write_text("\n".join(git_results),encoding="utf-8")
        py=str(ROOT/".venv/Scripts/python.exe");test_files=[str(x) for x in sorted((ROOT/"tests").glob("test_v5_1_*.py"))]
        checks=[
            [py,"-m","pytest","-q",*test_files],
            [py,"-m","pytest","-q"],
            [py,"scripts/project_status.py"],
            [py,"-m","v5.independence_audit"],
            ["powershell","-NoProfile","-ExecutionPolicy","Bypass","-File",str(ROOT/"scripts/audit_production_tasks.ps1")],
            ["git","diff","--check"],
        ]
        results=[];failed=[]
        for command in checks:
            code,out=run(command);results.append(f"> {' '.join(command)}\nexit_code={code}\n{out}")
            if code:failed.append(" ".join(command))
        clean=stage/"clean_room";shutil.copytree(release,clean)
        env=os.environ.copy();env["PYTHONPATH"]=""
        isolation=[py,"-c","import os,sys,shared_core,v5_1;print('cwd='+os.getcwd());print('shared_core.__file__='+shared_core.__file__);print('v5_1.__file__='+v5_1.__file__);print('repo_source_on_sys_path='+str(any(p.startswith(r'C:\\\\Users\\\\lisha\\\\stock-screener') and '.venv' not in p for p in sys.path)))"]
        for command in (isolation,[py,"-m","v5_1.production_acceptance","--release-root",str(clean),"--release-only"]):
            code,out=run(command,cwd=clean,env=env);results.append(f"> {' '.join(command)}\nexit_code={code}\n{out}")
            if code:failed.append(" ".join(command))
        (stage/"RC1_TEST_AND_ACCEPTANCE_RESULTS.txt").write_text("\n".join(results),encoding="utf-8")
        for cache in sorted(stage.rglob("__pycache__"),reverse=True):shutil.rmtree(cache)
        for compiled in stage.rglob("*.pyc"):compiled.unlink()
        identity={"release_id":manifest["release_id"],"git_commit_sha":manifest["git_sha"],"git_tree_sha":manifest["git_tree_sha"],"artifact_sha256":sha(RC),"release_manifest_sha256":sha(release/"RELEASE_MANIFEST.json"),"dependency_lock_sha256":sha(release/"requirements-v5_1.lock"),"source_inventory_sha256":sha(release/"SOURCE_INVENTORY.json"),"manifest_sha256":sha(release/"MANIFEST_SHA256.json"),"config_hash":manifest["config_hash"],"release_scope_dirty":manifest["release_scope_dirty"],"repository_overall_dirty":manifest["repository_overall_dirty"],"real_window_strict_days":0,"production_owner":"v5","production_cutover_authorized":False,"cutover_ready":False,"strategy_effectiveness":"UNPROVEN"}
        (stage/"RC1_IDENTITY.json").write_text(json.dumps(identity,indent=2,sort_keys=True),encoding="utf-8")
        note=f"""# V5.1-RC1 ChatGPT Review Manifest

This package reviews exact frozen commit `{RC_COMMIT}` and artifact `{RC.name}`.
It does not treat unrelated G1/V5 working-tree changes as RC content.

- Release scope: `release/` plus the exact commit diff in `GIT_RC1_EVIDENCE.txt`.
- Release-scope status: CLEAN.
- Repository overall status: DIRTY only because excluded G1, historical V5 and user artifacts remain.
- Clean-room acceptance and raw test/audit output: `RC1_TEST_AND_ACCEPTANCE_RESULTS.txt`.
- Blocking command failures: {failed or 'none'}.
- `research_locked=true`; `broker_orders=false`; production owner remains V5.
- Natural SHADOW has not started; strict natural round-trip days remain 0.
- CUTOVER READY=NO; strategy effectiveness=UNPROVEN.

The `release/` and `clean_room/` trees intentionally duplicate the exact RC payload so reviewers can inspect source and reproduce isolated imports without extracting the nested artifact.
"""
        (stage/"V5_1_RC1_REVIEW_MANIFEST.md").write_text(note,encoding="utf-8")
        rows=[]
        for path in sorted(x for x in stage.rglob("*") if x.is_file() and x.name!="MANIFEST_SHA256.csv"):
            rows.append((path.relative_to(stage).as_posix(),sha(path)))
        with (stage/"MANIFEST_SHA256.csv").open("w",encoding="utf-8",newline="") as handle:
            writer=csv.writer(handle);writer.writerow(["path","sha256"]);writer.writerows(rows)
        OUT.unlink(missing_ok=True)
        with zipfile.ZipFile(OUT,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            for path in sorted(x for x in stage.rglob("*") if x.is_file()):archive.write(path,path.relative_to(stage))
    print(OUT);print(f"sha256={sha(OUT)}")
    return 1 if failed else 0

if __name__=="__main__":raise SystemExit(main())
