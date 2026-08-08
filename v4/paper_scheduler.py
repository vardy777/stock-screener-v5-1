"""Admin-free scheduler hosted by the always-on local V4 dashboard."""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, time as wall_time
from pathlib import Path

from v4.calendar import TradingCalendar
from v4.execution import CHINA_TZ


ROOT = Path(__file__).resolve().parent.parent
RECEIPT_DIR = ROOT / "v4" / "data" / "paper_receipts"
logger = logging.getLogger(__name__)


class PaperScheduler:
    def __init__(self, receipt_dir: Path | None = None):
        self.receipt_dir = Path(receipt_dir) if receipt_dir else RECEIPT_DIR

    def _receipt(self, trade_date: str, mode: str) -> Path:
        return self.receipt_dir / f"{trade_date}-{mode}.json"

    def _save(self, trade_date: str, mode: str, result: dict) -> None:
        self.receipt_dir.mkdir(parents=True, exist_ok=True)
        path = self._receipt(trade_date, mode)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "trade_date": trade_date, "mode": mode,
            "executed_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
            "result": result,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def tick(self, current: datetime | None = None) -> dict | None:
        current = current or datetime.now(CHINA_TZ)
        current_date = current.date()
        if TradingCalendar().is_open(current_date) is not True:
            return None
        clock = current.timetz().replace(tzinfo=None)
        mode = None
        if wall_time(9, 30, 20) <= clock <= wall_time(9, 35, 59):
            mode = "sell"
        elif wall_time(14, 50, 40) <= clock <= wall_time(14, 51, 50):
            mode = "buy"
        if mode is None:
            return None
        trade_date = current_date.isoformat()
        if self._receipt(trade_date, mode).exists():
            return None

        from v4.simulation import SimulationEngine
        engine = SimulationEngine()
        engine.load_state()
        if mode == "buy":
            result = engine.execute_buy(refresh_candidates=False, paper_observation=True)
            complete = bool(result.get("success"))
        else:
            before = len(engine.positions)
            result = engine.execute_sell()
            complete = bool(result.get("success")) and (
                before == 0 or int(result.get("sold", 0)) == before
            )
        if complete:
            self._save(trade_date, mode, result)
        logger.info("V4 paper scheduler %s: %s", mode, result)
        return result


def start_paper_scheduler(poll_seconds: int = 5) -> threading.Thread:
    scheduler = PaperScheduler()

    def loop() -> None:
        while True:
            try:
                scheduler.tick()
            except Exception:
                logger.exception("V4 paper scheduler tick failed")
            time.sleep(max(1, poll_seconds))

    thread = threading.Thread(target=loop, name="v4-paper-scheduler", daemon=True)
    thread.start()
    return thread
