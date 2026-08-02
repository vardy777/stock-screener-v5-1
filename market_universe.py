"""Canonical A-share universe shared by live and research pipelines.

The strategy intentionally excludes STAR Market, Beijing Stock Exchange and
B-share symbols.  Do not generate synthetic numeric ranges: doing so both
misses valid boards (for example 601/603/605/002/003) and can accidentally
include 200/900 B-share series.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Optional


def normalize_code(value) -> str:
    """Return a six-digit security code or an empty string."""

    match = re.search(r"(\d{6})", str(value or ""))
    return match.group(1) if match else ""


def is_eligible_a_share(value) -> bool:
    """Whether *value* belongs to a supported Shanghai/Shenzhen A-share board."""

    code = normalize_code(value)
    if not code:
        return False
    if code.startswith(("000", "001", "002", "003")):
        return True
    if code.startswith("30"):
        return True
    return code.startswith(("600", "601", "603", "605"))


def filter_universe_codes(values: Iterable[object]) -> List[str]:
    return sorted(
        {
            code
            for value in values
            if (code := normalize_code(value)) and is_eligible_a_share(code)
        }
    )


def list_universe_codes(
    daily_dir: Path, *, maximum: Optional[int] = None
) -> List[str]:
    """Load the canonical live universe from the maintained market archive."""

    paths = sorted(Path(daily_dir).glob("*.csv"))
    codes = filter_universe_codes(path.stem for path in paths)
    if maximum is not None:
        return codes[: max(0, int(maximum))]
    return codes
