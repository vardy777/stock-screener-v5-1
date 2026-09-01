"""Strict provenance and coverage checks for the local exchange calendar."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Iterable, Tuple
from urllib.parse import urlparse
from .core import strict_bool


OFFICIAL_HOSTS = ("sse.com.cn", "szse.cn")


def _official_source(value: Any) -> bool:
    try:
        parsed = urlparse(str(value).strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        return parsed.scheme == "https" and any(
            host == official or host.endswith("." + official)
            for official in OFFICIAL_HOSTS
        )
    except (TypeError, ValueError):
        return False


def _open_value(value: Any):
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes"}:
        return True
    if text in {"0", "false", "no"}:
        return False
    return None


def _whole_year(year: int):
    current = date(year, 1, 1)
    end = date(year, 12, 31)
    while current <= end:
        yield current
        current += timedelta(days=1)


def validate_calendar_records(
    records: Iterable[Dict[str, Any]],
    *,
    require_complete_year: bool = True,
    today: date | None = None,
) -> Tuple[bool, Dict[str, bool], dict]:
    """Validate calendar rows without trusting substrings or partial coverage."""

    strict_bool(require_complete_year,"require_complete_year")

    current_day = today or date.today()
    sessions: Dict[str, bool] = {}
    sources = set()
    verified_dates = set()
    error = ""
    rows = list(records)
    if not rows:
        return False, {}, {"error": "calendar is empty"}
    required = {"date", "is_open", "source_url", "verified_at"}
    for row in rows:
        if not required.issubset(row):
            error = "calendar columns are incomplete"
            break
        try:
            session_date = date.fromisoformat(str(row["date"]).strip())
            verified_at = date.fromisoformat(str(row["verified_at"]).strip())
        except (TypeError, ValueError):
            error = "calendar contains an invalid date"
            break
        if verified_at > current_day:
            error = "calendar verification date is in the future"
            break
        source = str(row["source_url"]).strip()
        if not _official_source(source):
            error = "calendar source is not an exact official HTTPS host"
            break
        is_open = _open_value(row["is_open"])
        if is_open is None:
            error = "calendar contains an invalid is_open value"
            break
        key = session_date.isoformat()
        if key in sessions:
            error = "calendar contains duplicate dates"
            break
        sessions[key] = is_open
        sources.add(source)
        verified_dates.add(verified_at.isoformat())

    if not error and require_complete_year:
        years = sorted({date.fromisoformat(key).year for key in sessions})
        for year in years:
            expected = {day.isoformat() for day in _whole_year(year)}
            actual = {key for key in sessions if key.startswith(f"{year:04d}-")}
            if actual != expected:
                error = f"calendar year {year} is not complete"
                break

    valid = bool(sessions) and not error
    metadata = {
        "error": error,
        "rows": len(sessions),
        "source_urls": sorted(sources),
        "verified_dates": sorted(verified_dates),
        "years": sorted({date.fromisoformat(key).year for key in sessions}),
        "complete_year_required": require_complete_year,
    }
    return valid, sessions if valid else {}, metadata
