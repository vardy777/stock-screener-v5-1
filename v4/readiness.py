"""Research, data, stress and model publication gates for V4."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .contracts import GateCheck, PIPELINE_ID, SYSTEM_VERSION
from .model_registry import PublishedModelRegistry


ROOT = Path(__file__).resolve().parent.parent
OVERNIGHT = ROOT / "phase1" / "data" / "overnight"


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


class ResearchReadiness:
    """Single source of truth for whether V4 may create executable orders."""

    def _normal_report(self) -> Tuple[Path, Dict[str, Any], bool]:
        strict = OVERNIGHT / "wf_report_strict" / "summary.json"
        full = OVERNIGHT / "wf_report" / "summary.json"
        smoke = OVERNIGHT / "wf_report_smoke_optimized" / "summary.json"
        if strict.exists():
            return strict, _load_json(strict), True
        if full.exists():
            return full, _load_json(full), True
        return smoke, _load_json(smoke), False

    def _stress_report(self, full_market: bool) -> Tuple[Path, Dict[str, Any]]:
        strict = OVERNIGHT / "wf_report_strict_stress" / "summary.json"
        if strict.exists():
            return strict, _load_json(strict)
        path = OVERNIGHT / "wf_report_stress" / "summary.json" if full_market else OVERNIGHT / "wf_report_smoke_optimized_stress" / "summary.json"
        return path, _load_json(path)

    def evaluate(self) -> Dict[str, Any]:
        normal_path, normal, full_market = self._normal_report()
        stress_path, stress = self._stress_report(full_market)
        registry = PublishedModelRegistry(OVERNIGHT / "model")
        training = registry.info

        trades = int(normal.get("trades", 0))
        strict_rows = int(normal.get("strict_1450_rows", 0))
        ci_low = float(normal.get("win_rate_ci_low_95", 0.0))
        profit_factor = float(normal.get("profit_factor", 0.0))
        consistency = float(normal.get("window_consistency", 0.0))
        drawdown = float(normal.get("max_drawdown", -1.0))
        stress_return = float(stress.get("cumulative_return", -1.0))
        stress_pf = float(stress.get("profit_factor", 0.0))
        proxy_rate = float(normal.get("proxy_trade_rate", 1.0))
        strict_buy_rate = float(normal.get("strict_buy_trade_rate", 0.0))
        strict_sell_rate = float(normal.get("strict_sell_trade_rate", 0.0))
        strict_feature_rate = float(normal.get("strict_feature_trade_rate", 0.0))
        order_book_rate = float(normal.get("order_book_verified_trade_rate", 0.0))
        order_book_liquidity_rate = float(
            normal.get("order_book_liquidity_trade_rate", 0.0)
        )
        calendar_trade_rate = float(normal.get("calendar_verified_trade_rate", 0.0))
        calendar_verified = bool(normal.get("calendar_verified", False))
        coverage = float(normal.get("minimum_buy_universe_coverage", 0.0))
        volume_unit_verified = bool(normal.get("volume_unit_verified", False))
        point_in_time_universe = bool(
            normal.get("point_in_time_universe_verified", False)
        )
        point_in_time_names = bool(
            normal.get("point_in_time_security_name_verified", False)
        )
        stress_strict = (
            float(stress.get("proxy_trade_rate", 1.0)) == 0.0
            and float(stress.get("strict_trade_rate", 0.0)) == 1.0
        )
        dataset_mode_strict = normal.get("dataset_mode") == "strict"
        lineage_verified = bool(normal.get("lineage_verified", False))
        same_dataset = bool(
            normal.get("dataset_sha256")
            and normal.get("dataset_sha256") == stress.get("dataset_sha256")
        )
        frozen_stress_policy = bool(stress.get("stress_policy_frozen", False))
        normal_report_hash = _sha256(normal_path)
        stress_report_hash = _sha256(stress_path)
        normal_window_path = normal_path.parent / "window_stats.csv"
        normal_window_hash = _sha256(normal_window_path)
        frozen_windows_complete = bool(
            int(stress.get("total_windows", 0) or 0) > 0
            and int(stress.get("frozen_policy_windows", 0) or 0)
            == int(stress.get("total_windows", -1) or -1)
        )
        report_lineage = bool(
            normal_report_hash
            and normal_window_hash
            and normal.get("window_stats_sha256") == normal_window_hash
            and stress.get("normal_report_sha256") == normal_report_hash
            and stress.get("normal_window_stats_sha256") == normal_window_hash
        )
        model_report_lineage = bool(
            registry.available
            and training.get("normal_report_sha256") == normal_report_hash
            and training.get("stress_report_sha256") == stress_report_hash
        )

        checks: List[GateCheck] = [
            GateCheck("full_market", "全市场报告", full_market, "是" if full_market else "300只smoke"),
            GateCheck("strict_dataset_mode", "严格数据集独立评估", dataset_mode_strict, str(normal.get("dataset_mode", "legacy"))),
            GateCheck("lineage", "数据/报告血缘一致", lineage_verified and same_dataset, "一致" if lineage_verified and same_dataset else "缺失或不一致"),
            GateCheck("frozen_policy_lineage", "压力测试冻结策略与普通报告一致", report_lineage and frozen_windows_complete, "一致" if report_lineage and frozen_windows_complete else "缺失或不一致"),
            GateCheck("exact_execution", "严格买卖执行", trades > 0 and strict_buy_rate == 1.0 and strict_sell_rate == 1.0, f"买{strict_buy_rate*100:.1f}% / 卖{strict_sell_rate*100:.1f}%"),
            GateCheck("strict_features", "严格14:49:59特征", strict_feature_rate == 1.0, f"{strict_feature_rate*100:.1f}%"),
            GateCheck("order_book", "买一/卖一执行价", order_book_rate == 1.0, f"{order_book_rate*100:.1f}%"),
            GateCheck("order_book_liquidity", "一档挂单量覆盖计划股数", order_book_liquidity_rate == 1.0, f"{order_book_liquidity_rate*100:.1f}%"),
            GateCheck("no_proxy", "样本外代理交易为0", proxy_rate == 0.0, f"{proxy_rate*100:.1f}%"),
            GateCheck("calendar", "交易日历已核验", calendar_verified and calendar_trade_rate == 1.0, "已核验" if calendar_verified else "未核验"),
            GateCheck("coverage", "全市场最小覆盖≥95%", coverage >= 0.95, f"{coverage*100:.1f}%"),
            GateCheck("point_in_time_universe", "逐日股票池来源已审计", point_in_time_universe, "已审计" if point_in_time_universe else "未审计"),
            GateCheck("point_in_time_names", "逐日ST/退市名称过滤已审计", point_in_time_names, "已审计" if point_in_time_names else "未审计"),
            GateCheck("volume_unit", "成交量单位已核验为股", volume_unit_verified, "已核验" if volume_unit_verified else "未核验"),
            GateCheck("sample_size", "样本外交易≥500", trades >= 500, f"{trades}笔"),
            GateCheck("win_ci", "胜率95%下限>50%", ci_low > 0.50, f"{ci_low*100:.1f}%"),
            GateCheck("profit_factor", "Profit Factor≥1.20", profit_factor >= 1.20, f"{profit_factor:.2f}"),
            GateCheck("window_consistency", "盈利窗口≥70%", consistency >= 0.70, f"{consistency*100:.1f}%"),
            GateCheck("drawdown", "最大回撤≤12%", drawdown >= -0.12, f"{drawdown*100:.1f}%"),
            GateCheck("stress", "冻结生产策略加倍滑点仍盈利", stress_return > 0 and stress_pf >= 1.0 and stress_strict and frozen_stress_policy and frozen_windows_complete, f"{stress_return*100:+.2f}% / PF {stress_pf:.2f}"),
            GateCheck("accepted", "研究准入通过", bool(normal.get("acceptance_pass", False)), "通过" if normal.get("acceptance_pass") else "未通过"),
            GateCheck("published_model", "生产模型及策略已发布", registry.available, "已发布" if registry.available else registry.error or "无模型"),
            GateCheck("model_report_lineage", "生产模型绑定当前准入与压力报告", model_report_lineage, "一致" if model_report_lineage else "缺失或不一致"),
        ]
        trade_enabled = all(check.passed for check in checks if check.required)
        if trade_enabled:
            status = "paper_ready"
            headline = "V4已通过研究门槛，可进入受控模拟盘"
        elif strict_rows == 0:
            status = "research_locked"
            headline = "V4研究锁定：等待真实14:50/09:30数据"
        else:
            status = "validation_failed"
            headline = "V4研究锁定：样本外准入未通过"

        updated_at = ""
        if normal_path.exists():
            updated_at = datetime.fromtimestamp(normal_path.stat().st_mtime).isoformat(
                timespec="minutes"
            )
        return {
            "system_version": SYSTEM_VERSION,
            "pipeline_id": PIPELINE_ID,
            "status": status,
            "headline": headline,
            "trade_enabled": trade_enabled,
            "shadow_enabled": True,
            "full_market": full_market,
            "normal_report": normal,
            "stress_report": stress,
            "normal_report_path": str(normal_path),
            "stress_report_path": str(stress_path),
            "updated_at": updated_at,
            "checks": [check.to_dict() for check in checks],
            "model": {
                "published": registry.available,
                "manifest": registry.manifest,
                "training": training,
                "error": registry.error,
            },
            "next_action": (
                "积累真实14:50买入和09:30成交快照，重建全市场数据集"
                if strict_rows == 0
                else "继续滚动验证并扩大独立样本"
            ),
        }
