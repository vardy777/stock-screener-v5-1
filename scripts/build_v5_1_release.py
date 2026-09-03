"""Build a deterministic, secret-free and self-contained V5.1 release artifact."""
from __future__ import annotations
import argparse,hashlib,json,shutil,subprocess,tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED,ZipFile,ZipInfo

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"V5_1_RELEASE_CANDIDATE_UNFROZEN.zip"
EXCLUDED={"data","shadow_data","replay","test_data","__pycache__","logs","cache"}
DOCS=("docs/V5_1_ARCHITECTURE.md","docs/V5_1_MIGRATION_ACCEPTANCE.md","docs/V5_1_RUNBOOK.md","docs/V5_1_PRODUCTION_CUTOVER.md","docs/V5_1_SHADOW_TASK_MANIFEST.md","docs/V5_1_ACCEPTANCE_CONTRACT.md","docs/V5_1_RELEASE_PROCESS.md","docs/V5_1_SSE_SECURITY_MASTER_CANONICALIZATION_CONTRACT.md")
RELEASE_SCOPE=("shared_core","v5_1","tests/test_v5_1_*.py","requirements-v5_1.lock","scripts/build_v5_1_release.py",*DOCS)

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def copy_tree(source,target):
    for path in sorted(source.rglob("*")):
        if not path.is_file() or any(x in EXCLUDED for x in path.parts) or path.suffix in {".pyc",".env"} or any(x in path.name.lower() for x in ("token","secret")):continue
        dest=target/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
def git(*args):return subprocess.run(["git",*args],cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL).stdout.strip()
def release_scope_dirty():
    concrete=["shared_core","v5_1","requirements-v5_1.lock","scripts/build_v5_1_release.py",*DOCS,*[str(x.relative_to(ROOT)) for x in sorted((ROOT/"tests").glob("test_v5_1_*.py"))]]
    return bool(git("status","--porcelain","--",*concrete))

def build(output=OUT,release_id=None):
    with tempfile.TemporaryDirectory() as tmp:
        stage=Path(tmp);copy_tree(ROOT/"shared_core",stage);copy_tree(ROOT/"v5_1",stage)
        for path in sorted((ROOT/"tests").glob("test_v5_1_*.py")):
            dest=stage/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
        for name in ("pytest.ini","requirements-v5_1.lock"):
            shutil.copy2(ROOT/name,stage/name)
        for name in DOCS:
            source=ROOT/name
            if source.exists():
                dest=stage/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
        inventory={p.relative_to(stage).as_posix():digest(p) for p in sorted(stage.rglob("*")) if p.is_file()}
        (stage/"SOURCE_INVENTORY.json").write_text(json.dumps(inventory,sort_keys=True,indent=2),encoding="utf-8")
        environment={"schema_version":"v5.1-environment-manifest-v1","python":"3.11+","platform":"Windows","timezone":"Asia/Shanghai","dependency_lock":"requirements-v5_1.lock","broker_orders":False,"research_locked":True}
        (stage/"ENVIRONMENT_MANIFEST.json").write_text(json.dumps(environment,sort_keys=True,indent=2),encoding="utf-8")
        inventory={p.relative_to(stage).as_posix():digest(p) for p in sorted(stage.rglob("*")) if p.is_file()}
        manifest_hash=hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(",",":")).encode()).hexdigest();dependency_hash=digest(stage/"requirements-v5_1.lock");config_hash=digest(stage/"v5_1/release_config_schema.json")
        scoped_dirty=release_scope_dirty()
        if release_id and scoped_dirty:raise RuntimeError("release scope is dirty; refusing frozen release")
        identity=release_id or "v5.1-unfrozen-"+manifest_hash[:16]
        release={"schema_version":"v5.1-release-manifest-v1","release_id":identity,"git_sha":git("rev-parse","HEAD"),"git_tree_sha":git("rev-parse","HEAD^{tree}"),"repository_overall_dirty":bool(git("status","--porcelain")),"release_scope_dirty":scoped_dirty,"build_timestamp":git("show","-s","--format=%cI","HEAD") if release_id else "UNFROZEN_REPRODUCIBLE_BUILD","source_manifest_hash":manifest_hash,"dependency_lock_hash":dependency_hash,"config_hash":config_hash,"production_cutover_authorized":False}
        (stage/"RELEASE_MANIFEST.json").write_text(json.dumps(release,sort_keys=True,indent=2),encoding="utf-8")
        hashes={p.relative_to(stage).as_posix():digest(p) for p in sorted(stage.rglob("*")) if p.is_file()};(stage/"MANIFEST_SHA256.json").write_text(json.dumps(hashes,sort_keys=True,indent=2),encoding="utf-8")
        output=Path(output);output.unlink(missing_ok=True)
        with ZipFile(output,"w",ZIP_DEFLATED,compresslevel=9) as archive:
            for path in sorted(p for p in stage.rglob("*") if p.is_file()):
                info=ZipInfo(path.relative_to(stage).as_posix(),(2026,1,1,0,0,0));info.compress_type=ZIP_DEFLATED;info.external_attr=0o644<<16;archive.writestr(info,path.read_bytes())
    return output
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--release-id");parser.add_argument("--output");args=parser.parse_args()
    output=Path(args.output) if args.output else ROOT/("V5_1_RC1.zip" if args.release_id=="V5.1-RC1" else OUT.name)
    path=build(output,args.release_id);print(path);print(hashlib.sha256(path.read_bytes()).hexdigest())
