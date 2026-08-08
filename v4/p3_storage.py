"""P3-compatible wrappers around shared isolated storage primitives."""

from contextlib import contextmanager

from .offline_storage import atomic_json_write
from .offline_storage import exclusive_file_lock as _exclusive_file_lock
from .p3_contracts import PaperContractViolation


@contextmanager
def exclusive_file_lock(path, *, timeout=2.0):
    with _exclusive_file_lock(path, timeout=timeout, error_type=PaperContractViolation):
        yield
