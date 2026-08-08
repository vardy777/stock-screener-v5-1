import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from v4.paper_scheduler import PaperScheduler


class PaperSchedulerTests(unittest.TestCase):
    def test_buy_runs_once_inside_window(self):
        with tempfile.TemporaryDirectory() as directory:
            scheduler = PaperScheduler(Path(directory))
            engine = MagicMock()
            engine.execute_buy.return_value = {"success": True, "bought": 1}
            now = datetime(2026, 8, 5, 14, 50, 45, tzinfo=ZoneInfo("Asia/Shanghai"))
            with patch("v4.paper_scheduler.TradingCalendar") as calendar:
                calendar.return_value.is_open.return_value = True
                with patch("v4.simulation.SimulationEngine", return_value=engine):
                    scheduler.tick(now)
                    scheduler.tick(now)
            engine.execute_buy.assert_called_once_with(
                refresh_candidates=False, paper_observation=True
            )


if __name__ == "__main__":
    unittest.main()
