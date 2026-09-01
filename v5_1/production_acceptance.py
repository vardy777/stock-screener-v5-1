"""One-command V5.1 release and production-readiness gate."""
from __future__ import annotations
import argparse,ast,hashlib,json,subprocess,sys
from pathlib import Path

def run(command,cwd):
    result=subprocess.run(command,cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    return result.returncode,result.stdout

def dependency_scan(root):
    bad=[]
    for path in (root/"v5_1").glob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom) and (node.module or "").startswith("v5"):bad.append(f"{path.name}:{node.lineno}:{node.module}")
            if isinstance(node,ast.Import):bad.extend(f"{path.name}:{node.lineno}:{x.name}" for x in node.names if x.name.startswith("v5"))
    return bad

def verify_release(root):
    manifest=root/"MANIFEST_SHA256.json"
    if not manifest.exists():return False,"MANIFEST_SHA256.json missing"
    rows=json.loads(manifest.read_text(encoding="utf-8"))
    for name,digest in rows.items():
        path=root/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:return False,f"hash mismatch: {name}"
    return True,f"{len(rows)} files verified"

def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument("--release-root",default=str(Path(__file__).resolve().parents[1]));parser.add_argument("--release-only",action="store_true");args=parser.parse_args(argv);root=Path(args.release_root).resolve();gates={};details={}
    bad=dependency_scan(root);gates["V5_DEPENDENCY_GATE"]=not bad;details["V5_DEPENDENCY_GATE"]=bad or "0 direct imports"
    code,out=run([sys.executable,"-m","compileall","-q","shared_core","v5_1"],root);gates["CODE_GATE"]=code==0;details["CODE_GATE"]=out[-2000:]
    strict=root/"tests/test_v5_1_strict_persisted.py";code,out=run([sys.executable,"-m","pytest","-q",str(strict)],root);gates["STRICT_TYPE_GATE"]=code==0;details["STRICT_TYPE_GATE"]=out[-2000:]
    files=[str(x) for x in sorted((root/"tests").glob("test_v5_1_*.py"))];code,out=run([sys.executable,"-m","pytest","-q",*files],root);gates["RUNTIME_GATE"]=code==0;details["RUNTIME_GATE"]=out[-2000:]
    if (root/"MANIFEST_SHA256.json").exists():ok,message=verify_release(root)
    else:ok,message=True,"source workspace (release manifest checked by builder)"
    gates["RELEASE_INTEGRITY_GATE"]=ok;details["RELEASE_INTEGRITY_GATE"]=message
    schema=json.loads((root/"v5_1/release_config_schema.json").read_text(encoding="utf-8"));gates["CONFIG_GATE"]=schema.get("required",{}).get("research_locked") is True and schema.get("required",{}).get("broker_orders") is False;details["CONFIG_GATE"]=schema.get("required")
    offline_pass=all(gates.values())
    if not args.release_only:
        gates.update({"NATURAL_WINDOW_GATE":False,"SCHEDULER_GATE":False,"SINGLE_WRITER_GATE":False,"CUTOVER_GATE":False,"ROLLBACK_GATE":False});details["blocking"]="natural shadow, actual Scheduler ownership, rollback drill and cutover authorization pending"
    passed=all(gates.values());payload={"schema_version":"v5.1-production-exit-acceptance-v1","result":"PASS" if passed else "FAIL","offline_release_pass":offline_pass,"gates":{k:("PASS" if v else "FAIL") for k,v in gates.items()},"details":details};print(json.dumps(payload,ensure_ascii=False,indent=2));return 0 if passed else 1

if __name__=="__main__":raise SystemExit(main())
