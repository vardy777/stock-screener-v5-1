"""Fail-closed storage primitives used only by isolated P3 journals."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import time

from .p3_contracts import PaperContractViolation


@contextmanager
def exclusive_file_lock(path: Path, *, timeout: float = 2.0):
    """Hold an OS process lock for an entire read/modify/write transaction."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    deadline = time.monotonic() + timeout
    locked = False
    try:
        while not locked:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    if handle.tell() == 0 and path.stat().st_size == 0:
                        handle.write(b"0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise PaperContractViolation("storage lock: contention timeout") from exc
                time.sleep(0.01)
        yield
    finally:
        if locked:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def atomic_json_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
