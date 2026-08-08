import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from v4.execution import CHINA_TZ, TradingClock
from v4.readiness import ResearchReadiness
from v4.runtime import V4Runtime
from v4.selection import V4CandidateSelector
from v4.snapshots import capture_frame


class V4Tests(unittest.TestCase):
    def test_scheduler_entrypoints_are_preserved(self):
        root = Path(__file__).resolve().parent.parent
        for relative in (
            "v3/scripts/afternoon_push.py",
            "v3/scripts/morning_push.py",
            "v3/scripts/watchlist_scan.py",
            "phase1/scripts/run_scheduled_capture.ps1",
            "phase1/scripts/run_scheduled_health.ps1",
            "phase1/scripts/run_scheduled_push.ps1",
            "phase1/scripts/run_dashboard_local.ps1",
            "phase1/scripts/run_daily_maintenance.ps1",
            "phase1/scripts/prepare_next_session.py",
            "phase1/scripts/test_pushplus.py",
        ):
            self.assertTrue((root / relative).exists(), relative)

    def test_clock_enforces_buy_sell_windows_and_weekends(self):
        monday_buy = datetime(2026, 8, 3, 14, 50, 30, tzinfo=CHINA_TZ)
        monday_sell = datetime(2026, 8, 3, 9, 30, 30, tzinfo=CHINA_TZ)
        saturday = datetime(2026, 8, 1, 14, 50, 30, tzinfo=CHINA_TZ)

        self.assertTrue(TradingClock.action_status("buy", now=monday_buy).allowed)
        self.assertTrue(TradingClock.action_status("sell", now=monday_sell).allowed)
        self.assertFalse(TradingClock.action_status("buy", now=saturday).allowed)
        self.assertFalse(TradingClock.action_status("sell", now=monday_buy).allowed)

    def test_clock_blocks_exchange_holiday_and_uncovered_year(self):
        holiday = datetime(2026, 10, 1, 14, 50, 30, tzinfo=CHINA_TZ)
        uncovered = datetime(2027, 1, 4, 14, 50, 30, tzinfo=CHINA_TZ)
        holiday_status = TradingClock.action_status("buy", now=holiday)
        uncovered_status = TradingClock.action_status("buy", now=uncovered)
        self.assertFalse(holiday_status.allowed)
        self.assertIn("休市", holiday_status.reason)
        self.assertFalse(uncovered_status.allowed)
        self.assertIn("交易日历", uncovered_status.reason)

    def test_current_proxy_report_keeps_v4_research_locked(self):
        readiness = ResearchReadiness().evaluate()
        self.assertFalse(readiness["trade_enabled"])
        self.assertEqual(readiness["status"], "research_locked")
        self.assertTrue(readiness["shadow_enabled"])

    def test_runtime_keeps_candidates_visible_but_non_tradable(self):
        runtime = V4Runtime()
        candidate = {
            "code": "000001",
            "name": "测试",
            "price": 10.0,
            "score": 92.0,
            "rank": 1,
            "quote_time": TradingClock.now().isoformat(),
            "v4_candidate_origin": "V4",
            "v4_research_ranked": True,
        }
        with patch("v4.runtime.save_runtime_state"):
            result = runtime.evaluate_candidates(
                [candidate], {"mode_label": "neutral", "advance_ratio": 0.6}
            )
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["v4_tradable"])
        self.assertIn("研究准入未通过", result[0]["v4_block_reasons"])
        self.assertIn("v4_shadow_confidence", result[0])

    def test_paper_candidate_can_use_complete_snapshot_without_unlocking_production(self):
        runtime = V4Runtime()
        candidate = {
            "code": "000001", "name": "测试", "price": 10.0,
            "score": 92.0, "rank": 1,
            "quote_time": "2026-08-06T14:50:30+08:00",
            "selection_stage": "confirmation_1450",
            "linkage_status": "confirmed_from_morning_pool",
            "v4_candidate_origin": "V4",
            "v4_research_ranked": True,
            "v4_paper_market_valid": True,
            "v4_paper_market_mode": "neutral",
            "base_score": 90.0,
            "confirm_delta": 2.0,
            "decision_score": 92.0,
            "score_version": "v4-base-plus-confirm-delta-v1",
        }
        status = SimpleNamespace(
            allowed=True, reason="处于允许窗口", to_dict=lambda: {}
        )
        with (
            patch("v4.runtime.TradingClock.action_status", return_value=status),
            patch("v4.runtime.TradingClock.quote_is_fresh", return_value=True),
            patch("v4.runtime.save_runtime_state"),
        ):
            result = runtime.evaluate_candidates([candidate], {
                "mode_label": "unavailable",
                "observed_mode_label": "neutral",
                "data_valid": False,
                "snapshot_complete": True,
                "quote_coverage": 0.998,
            })
        self.assertTrue(result[0]["v4_paper_eligible"])
        self.assertFalse(result[0]["v4_tradable"])
        self.assertIn("全市场状态数据无效或覆盖不足", result[0]["v4_block_reasons"])

    def test_runtime_ignores_legacy_fallback_candidates(self):
        runtime = V4Runtime()
        selector = MagicMock()
        selector.select_research.return_value = [{
            "code": "000001", "name": "V4候选", "price": 10.0,
            "score": 88.0, "rank": 1,
            "quote_time": "2026-08-03T09:25:00+08:00",
            "v4_candidate_origin": "V4", "v4_research_ranked": True,
            "candidate_source": "v4-causal-rule-rank-v1",
        }]
        selector.last_diagnostics = {
            "status": "ranked", "source": "v4-causal-rule-rank-v1"
        }
        runtime.candidate_selector = selector
        status = SimpleNamespace(
            allowed=False, reason="不在买入窗口", to_dict=lambda: {}
        )
        with (
            patch("v4.runtime.TradingClock.action_status", return_value=status),
            patch("v4.runtime.TradingClock.quote_is_fresh", return_value=True),
            patch("v4.runtime.save_runtime_state"),
        ):
            result = runtime.evaluate_universe(
                pd.DataFrame([{"code": "000001"}]),
                fallback_candidates=[{"code": "999999", "name": "旧候选"}],
                market_state={"mode_label": "neutral", "data_valid": True},
            )
        self.assertEqual([item["code"] for item in result], ["000001"])
        self.assertEqual(result[0]["v4_candidate_origin"], "V4")

    def test_v4_research_selector_builds_candidates_from_full_market_context(self):
        with TemporaryDirectory() as temp_dir:
            context_path = Path(temp_dir) / "context.csv.gz"
            base = {
                "context_date": "2026-07-31",
                "context_prev_close": 10.0,
                "volume_mean_20": 1_000_000,
                "ma5_base": 9.8,
                "ma10_base": 9.7,
                "ma20_base": 9.5,
                "ret_1d": 0.01,
                "ret_3d": 0.02,
                "ret_5d": 0.03,
                "ret_10d": 0.04,
                "ret_20d": 0.05,
                "volatility_20": 0.02,
                "overnight_mean_20": 0.002,
                "overnight_hit_1pct_20": 0.25,
            }
            context = pd.DataFrame([
                {"code": "000001", **base},
                {"code": "000002", **{**base, "ret_5d": 0.01}},
                {"code": "000003", **{**base, "ret_5d": -0.01}},
            ])
            context.to_csv(context_path, index=False, compression="gzip")
            context_path.with_suffix(context_path.suffix + ".meta.json").write_text(
                json.dumps({
                    "strict_context_ready": True,
                    "expected_previous_session": "2026-07-31",
                }),
                encoding="utf-8",
            )
            quotes = pd.DataFrame([
                {
                    "code": f"00000{number}", "name": f"股票{number}",
                    "price": 10.0 + number * 0.05, "prev_close": 10.0,
                    "open": 10.0, "high": 10.2, "low": 9.9,
                    "volume": 100_000 * number, "amount": 50_000_000 * number,
                    "ask1": 10.01 + number * 0.05,
                    "quote_time": "2026-08-03T09:25:00+08:00",
                    "change_pct": number * 0.5,
                }
                for number in range(1, 4)
            ])
            selector = V4CandidateSelector(context_path=context_path)
            with patch("v4.selection.TradingClock.quote_is_fresh", return_value=True):
                result = selector.select_research(
                    quotes,
                    {
                        "data_valid": True, "mode_label": "neutral",
                        "advance_ratio": 0.60,
                        "market_mean_signal_return": 0.002,
                        "market_mean_gap": 0.0,
                        "regime_score": 0.2,
                        "fresh_quote_coverage": 1.0,
                    },
                    require_frozen_features=False,
                )
        self.assertTrue(result)
        self.assertTrue(all(item["v4_candidate_origin"] == "V4" for item in result))
        self.assertTrue(all(item["candidate_source"] == "v4-causal-rule-rank-v1" for item in result))
        self.assertTrue(all(item["selection_stage"] == "morning_observation" for item in result))
        self.assertEqual(selector.last_diagnostics["status"], "ranked")

    def test_snapshot_keeps_only_fresh_non_mock_rows_in_exact_window(self):
        now = datetime(2026, 8, 3, 14, 50, 30, tzinfo=CHINA_TZ)
        frame = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "正常股票",
                    "price": 10.0,
                    "quote_time": now.isoformat(),
                    "is_mock": False,
                },
                {
                    "code": "000002",
                    "name": "模拟股票",
                    "price": 11.0,
                    "quote_time": now.isoformat(),
                    "is_mock": True,
                },
                {
                    "code": "000003",
                    "name": "过期股票",
                    "price": 12.0,
                    "quote_time": "2026-08-03T14:40:00+08:00",
                    "is_mock": False,
                },
            ]
        )
        with TemporaryDirectory() as temp_dir:
            with patch("v4.snapshots.SNAPSHOT_ROOT", Path(temp_dir)):
                output = capture_frame(frame, "buy", now=now)
                self.assertIsNotNone(output)
                saved = pd.read_csv(output, dtype={"code": str})
                manifest = json.loads(
                    output.with_suffix(output.suffix + ".meta.json").read_text(
                        encoding="utf-8"
                    )
                )

        self.assertEqual(saved["code"].tolist(), ["000001"])
        self.assertTrue(saved["quote_is_fresh"].all())
        self.assertTrue(saved["window_valid"].all())
        self.assertFalse(saved["is_mock"].all())
        self.assertTrue(manifest["causal_quote_time_required"])

    def test_future_quotes_and_low_coverage_are_rejected(self):
        now = datetime(2026, 8, 3, 14, 50, 30, tzinfo=CHINA_TZ)
        self.assertFalse(
            TradingClock.quote_is_fresh((now + timedelta(seconds=1)).isoformat(), now=now)
        )
        frame = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "正常股票",
                    "price": 10.0,
                    "quote_time": now.isoformat(),
                }
            ]
        )
        with TemporaryDirectory() as temp_dir:
            with patch("v4.snapshots.SNAPSHOT_ROOT", Path(temp_dir)):
                output = capture_frame(
                    frame,
                    "buy",
                    now=now,
                    expected_codes=["000001", "000002"],
                    minimum_coverage=0.95,
                )
                self.assertIsNone(output)
                self.assertEqual(list(Path(temp_dir).rglob("*.csv")), [])

    def test_strict_buy_snapshot_uses_ask1_not_last_price(self):
        now = datetime(2026, 8, 3, 14, 50, 30, tzinfo=CHINA_TZ)
        frame = pd.DataFrame(
            [
                {
                    "code": "000001",
                    "name": "正常股票",
                    "price": 10.00,
                    "ask1": 10.02,
                    "ask1_volume": 20_000,
                    "bid1": 9.99,
                    "bid1_volume": 18_000,
                    "quote_time": now.isoformat(),
                }
            ]
        )
        with TemporaryDirectory() as temp_dir:
            with patch("v4.snapshots.SNAPSHOT_ROOT", Path(temp_dir)):
                output = capture_frame(
                    frame,
                    "buy",
                    now=now,
                    expected_codes=["000001"],
                    require_order_book=True,
                )
                saved = pd.read_csv(output, dtype={"code": str})
        self.assertEqual(float(saved.iloc[0]["last_price"]), 10.0)
        self.assertEqual(float(saved.iloc[0]["price"]), 10.02)
        self.assertEqual(saved.iloc[0]["execution_price_source"], "ask1")
        self.assertTrue(saved.iloc[0]["order_book_verified"])

    def test_snapshot_rejects_outside_window_and_unknown_session(self):
        outside = datetime(2026, 8, 3, 14, 49, 59, tzinfo=CHINA_TZ)
        frame = pd.DataFrame(
            [{"code": "000001", "name": "测试", "price": 10.0, "quote_time": outside.isoformat()}]
        )
        self.assertIsNone(capture_frame(frame, "buy", now=outside))
        self.assertIsNone(capture_frame(frame, "other", now=outside))


if __name__ == "__main__":
    unittest.main()
