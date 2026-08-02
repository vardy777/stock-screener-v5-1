"""Small atomic runtime snapshot store used by the dashboard and operators."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "v4" / "data"
STATE_PATH = DATA_DIR / "runtime_state.json"


def save_runtime_state(state: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, default=str)
    temporary.replace(STATE_PATH)


def load_runtime_state() -> Dict[str, Any]:
    try:
        with STATE_PATH.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}

