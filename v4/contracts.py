"""Stable dictionaries and identifiers shared by V4 adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


SYSTEM_VERSION = "4.0.0-research"
PIPELINE_ID = "overnight-1450-0930"


@dataclass(frozen=True)
class GateCheck:
    key: str
    label: str
    passed: bool
    value: str
    required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionStatus:
    action: str
    allowed: bool
    reason: str
    window: str
    now: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

