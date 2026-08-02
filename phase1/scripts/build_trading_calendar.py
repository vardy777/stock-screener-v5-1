#!/usr/bin/env python3
"""Generate the verified 2026 A-share calendar from the SSE holiday notice."""

import argparse
import csv
from datetime import date, timedelta
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent
SOURCE_URL = "https://www.sse.com.cn/disclosure/dealinstruc/closed/"
VERIFIED_AT = "2026-08-01"

# Weekends are handled independently.  These are the weekday closures in the
# SSE 2026 annual holiday notice.
CLOSED_WEEKDAYS_2026 = {
    date(2026, 1, 1), date(2026, 1, 2),
    date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18),
    date(2026, 2, 19), date(2026, 2, 20), date(2026, 2, 23),
    date(2026, 4, 6),
    date(2026, 5, 1), date(2026, 5, 4), date(2026, 5, 5),
    date(2026, 6, 19),
    date(2026, 9, 25),
    date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5),
    date(2026, 10, 6), date(2026, 10, 7),
}


def build_rows(year: int):
    if year != 2026:
        raise ValueError("only the officially verified 2026 schedule is bundled")
    current = date(year, 1, 1)
    end = date(year, 12, 31)
    while current <= end:
        is_open = current.weekday() < 5 and current not in CLOSED_WEEKDAYS_2026
        yield {
            "date": current.isoformat(),
            "is_open": int(is_open),
            "source_url": SOURCE_URL,
            "verified_at": VERIFIED_AT,
        }
        current += timedelta(days=1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument(
        "--output",
        type=Path,
        default=BASE / "data" / "trading_calendar_cn.csv",
    )
    args = parser.parse_args()
    rows = list(build_rows(args.year))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["date", "is_open", "source_url", "verified_at"]
        )
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(args.output)
    print(f"calendar rows={len(rows)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

