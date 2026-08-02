"""Atomic JSON cache for the V3 watchlist dashboard/push handoff."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from v3.config import DATA_DIR


CACHE_FILE = Path(DATA_DIR) / "watchlist_cache.json"


def save_cache(results: List[Dict], path: Optional[Path] = None) -> Path:
    target = Path(path) if path is not None else CACHE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = results if isinstance(results, list) else []
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
    temporary.replace(target)
    return target


def load_cache(path: Optional[Path] = None) -> List[Dict]:
    target = Path(path) if path is not None else CACHE_FILE
    try:
        with target.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, list) else []
    except (OSError, TypeError, ValueError):
        return []

