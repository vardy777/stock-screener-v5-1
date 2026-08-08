"""Content-addressed offline backup and isolated restore verification."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile


class BackupViolation(ValueError): pass


def _sha(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()


def create_backup(source: Path, destination: Path, *, created_at: datetime) -> Path:
    source=Path(source).resolve(); destination=Path(destination).resolve()
    if created_at.tzinfo is None: raise BackupViolation("created_at must be timezone-aware")
    if not source.is_dir(): raise BackupViolation("source directory missing")
    if destination == source or source in destination.parents: raise BackupViolation("destination must be outside source")
    rows=[]
    for path in sorted(x for x in source.rglob("*") if x.is_file()):
        rel=path.relative_to(source).as_posix(); raw=path.read_bytes()
        rows.append({"path":rel,"size":len(raw),"sha256":_sha(raw)})
    manifest={"schema_version":"v4-backup-manifest-v1","created_at":created_at.isoformat(timespec="seconds"),
              "files":rows}
    manifest_raw=json.dumps(manifest,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    backup_id="backup1-"+_sha(manifest_raw)[:24]; destination.mkdir(parents=True,exist_ok=True)
    target=destination/f"{backup_id}.zip"; temporary=target.with_suffix(".tmp")
    if target.exists(): return target
    with zipfile.ZipFile(temporary,"w",compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("MANIFEST.json",manifest_raw)
        for row in rows: bundle.writestr("payload/"+row["path"],(source/Path(row["path"])).read_bytes())
    temporary.replace(target); return target


def verify_backup(bundle_path: Path) -> dict:
    reasons=[]
    try:
        with zipfile.ZipFile(bundle_path,"r") as bundle:
            names=bundle.namelist(); manifest=json.loads(bundle.read("MANIFEST.json"))
            expected={"payload/"+x["path"]:x for x in manifest.get("files",[])}
            if set(names)!={"MANIFEST.json",*expected}: reasons.append("UNDECLARED_OR_MISSING_MEMBER")
            for name,row in expected.items():
                pure=PurePosixPath(name)
                if pure.is_absolute() or ".." in pure.parts: reasons.append("UNSAFE_MEMBER:"+name); continue
                try: raw=bundle.read(name)
                except KeyError: continue
                if len(raw)!=row.get("size") or _sha(raw)!=row.get("sha256"): reasons.append("HASH_MISMATCH:"+name)
    except (OSError,ValueError,KeyError,zipfile.BadZipFile) as exc:
        reasons.append("INVALID_BUNDLE:"+str(exc)); manifest={}
    return {"schema_version":"v4-backup-verification-v1","passed":not reasons,"reasons":reasons,
            "files":len(manifest.get("files",[]))}


def restore_to_empty(bundle_path: Path, destination: Path) -> dict:
    destination=Path(destination)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise BackupViolation("restore destination must be an empty directory")
    verification=verify_backup(bundle_path)
    if not verification["passed"]: raise BackupViolation("backup verification failed")
    destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(bundle_path,"r") as bundle:
        manifest=json.loads(bundle.read("MANIFEST.json"))
        for row in manifest["files"]:
            target=(destination/row["path"]).resolve()
            if destination.resolve() not in target.parents: raise BackupViolation("unsafe restore path")
            target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(bundle.read("payload/"+row["path"]))
    return {"status":"RESTORED_AND_VERIFIED",**verify_tree(destination,manifest)}


def verify_tree(destination: Path, manifest: dict) -> dict:
    actual=[]
    for path in sorted(x for x in Path(destination).rglob("*") if x.is_file()):
        raw=path.read_bytes(); actual.append({"path":path.relative_to(destination).as_posix(),"size":len(raw),"sha256":_sha(raw)})
    return {"passed":actual==manifest.get("files",[]),"files":len(actual)}
