"""Small atomic runtime snapshot store used by the dashboard and operators."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from .offline_storage import atomic_json_write,exclusive_file_lock


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "v4" / "data"
STATE_PATH = DATA_DIR / "runtime_state.json"


def save_runtime_state(state: Dict[str, Any]) -> None:
    with exclusive_file_lock(STATE_PATH.with_suffix(".lock")):
        atomic_json_write(STATE_PATH,json.loads(json.dumps(state,default=str)))


def load_runtime_state() -> Dict[str, Any]:
    try:
        with STATE_PATH.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}
