import ast
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).parents[1]

def test_v51_runtime_has_zero_direct_v5_imports():
    violations=[]
    for path in (ROOT/"v5_1").glob("*.py"):
        tree=ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom) and (node.module or "").startswith("v5"):violations.append((path.name,node.lineno,node.module))
            if isinstance(node,ast.Import):
                violations.extend((path.name,node.lineno,x.name) for x in node.names if x.name.startswith("v5"))
    assert violations==[]

def test_v51_imports_without_v5_package_in_isolated_copy(tmp_path):
    shutil.copytree(ROOT/"v5_1",tmp_path/"v5_1",ignore=shutil.ignore_patterns("data","shadow_data","replay","test_data","__pycache__"));shutil.copytree(ROOT/"shared_core",tmp_path/"shared_core",ignore=shutil.ignore_patterns("__pycache__"))
    result=subprocess.run([sys.executable,"-I","-c","import sys;sys.path.insert(0,r'%s');import v5_1.runtime,v5_1.dashboard;print('INDEPENDENT_OK')"%tmp_path],text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=="INDEPENDENT_OK"
