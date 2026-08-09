"""Read-only local operational checks used before a cutover or trading day."""

from __future__ import annotations

import shutil
from datetime import datetime,timezone
from pathlib import Path


def audit_log_retention(project_root: Path, *, max_bytes=50*1024*1024, retention_days=30, now=None) -> dict:
    root=Path(project_root).resolve(); now=now or datetime.now(timezone.utc); rows=[]
    for directory in (root/"v4"/"logs",root/"phase1"/"data"/"logs"):
        for path in sorted(directory.glob("*.log")) if directory.is_dir() else []:
            stat=path.stat(); age=max(0,(now.timestamp()-stat.st_mtime)/86400)
            rows.append({"path":str(path),"size":stat.st_size,"age_days":round(age,2),
                         "rotation_candidate":stat.st_size>max_bytes,"retention_candidate":age>retention_days})
    return {"schema_version":"log-retention-audit-v1","policy":{"max_bytes":max_bytes,"retention_days":retention_days},
            "logs":rows,"mutation_performed":False}


def operational_preflight(project_root: Path, *, minimum_free_gib=2.0) -> dict:
    root=Path(project_root).resolve(); checks=[]
    def add(name,passed,detail): checks.append({"name":name,"passed":bool(passed),"detail":detail})
    add("project_root",root.is_dir(),str(root))
    add("venv_python",(root/".venv"/"Scripts"/"python.exe").is_file(),str(root/".venv"/"Scripts"/"python.exe"))
    add("env_local_present",(root/"v4"/".env").is_file(),"local secret file present")
    free=shutil.disk_usage(root).free/(1024**3); add("disk_free",free>=minimum_free_gib,f"{free:.2f} GiB")
    for name in ("candidate_journal","paper_receipts"):
        path=root/"v4"/"data"/name; add("directory_"+name,path.is_dir(),str(path))
    add("p5_not_connected", "p5_" not in (root/"v4"/"dashboard.py").read_text(encoding="utf-8"),"8898 legacy entry unchanged")
    return {"schema_version":"operations-preflight-v1","passed":all(x["passed"] for x in checks),
            "checks":checks,"log_retention":audit_log_retention(root),"read_only":True,"production_mutated":False}
