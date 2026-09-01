from __future__ import annotations
import hashlib,json,os
from pathlib import Path
from shared_core.core import ContractViolation

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))

def content_id(prefix,value):
    return prefix+"-"+hashlib.sha256(canonical(value).encode()).hexdigest()

def save_immutable(path,payload):
    path=Path(path);raw=canonical(payload);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8")!=raw:raise ContractViolation("immutable fact collision")
        return path
    tmp=path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
    try:os.link(tmp,path)
    except FileExistsError:
        if path.read_text(encoding="utf-8")!=raw:raise ContractViolation("immutable fact collision")
    finally:tmp.unlink(missing_ok=True)
    return path

