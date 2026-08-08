"""Machine-local configuration for the standalone V4 runtime."""

from __future__ import annotations

import os
from pathlib import Path

from strategy_spec import DEFAULT_SPEC


ROOT = Path(__file__).resolve().parent.parent
V4_DIR = ROOT / "v4"
DATA_DIR = str(V4_DIR / "data")
SCRIPTS_DIR = str(V4_DIR / "scripts")

env_file = V4_DIR / ".env"
if env_file.exists():
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

PUSHPLUS_TOKEN = os.getenv("PUSHPLUS_TOKEN", "")
POSITION_SIZE = DEFAULT_SPEC.max_position_fraction

Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
Path(SCRIPTS_DIR).mkdir(parents=True, exist_ok=True)
