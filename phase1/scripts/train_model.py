#!/usr/bin/env python3
"""Publish a lineage-bound model and its exact validated Top1 policy."""

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))

from overnight import FEATURE_COLUMNS, fit_final_model_and_policy, load_research_dataset
from strategy_spec import DEFAULT_SPEC


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: dict) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")


def _write_json_atomic(value: dict, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_json_bytes(value))
    temporary.replace(path)


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}


def _gate_passed(
    normal: dict,
    stress: dict,
    dataset_sha256: str,
    *,
    normal_report_sha256: str,
    normal_window_sha256: str,
) -> bool:
    return bool(
        normal.get("acceptance_pass", False)
        and normal.get("dataset_mode") == "strict"
        and normal.get("lineage_verified", False)
        and normal.get("dataset_sha256") == dataset_sha256
        and stress.get("dataset_mode") == "strict"
        and stress.get("lineage_verified", False)
        and stress.get("dataset_sha256") == dataset_sha256
        and stress.get("normal_report_sha256") == normal_report_sha256
        and normal.get("window_stats_sha256") == normal_window_sha256
        and stress.get("normal_window_stats_sha256") == normal_window_sha256
        and stress.get("stress_policy_frozen", False)
        and stress.get("frozen_policy_windows", 0)
        == stress.get("total_windows", -1)
        and normal.get("proxy_trade_rate", 1.0) == 0.0
        and normal.get("strict_trade_rate", 0.0) == 1.0
        and stress.get("cumulative_return", 0.0) > 0.0
        and stress.get("profit_factor", 0.0) >= 1.0
        and stress.get("proxy_trade_rate", 1.0) == 0.0
        and stress.get("strict_trade_rate", 0.0) == 1.0
        and normal.get("point_in_time_universe_verified", False)
        and normal.get("point_in_time_security_name_verified", False)
        and stress.get("point_in_time_universe_verified", False)
        and stress.get("point_in_time_security_name_verified", False)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--max-stocks", type=int, default=None)
    parser.add_argument("--model", choices=["auto", "ridge", "lightgbm"], default="auto")
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument(
        "--dataset-mode", choices=["strict", "proxy"], default="strict"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="仅生成隔离的research_only诊断模型，永不发布",
    )
    args = parser.parse_args()
    if args.dataset_mode != "strict" and not args.force:
        print("拒绝发布: 生产模型只能使用strict数据集")
        return 2

    cache = args.cache or (BASE / "data" / "overnight" / "dataset.csv.gz")
    try:
        dataset, metadata, selected_cache = load_research_dataset(
            BASE / "data" / "daily",
            cache,
            spec=DEFAULT_SPEC,
            dataset_mode=args.dataset_mode,
            rebuild=args.rebuild,
            max_stocks=args.max_stocks,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"拒绝训练最终模型: {exc}")
        return 2
    if dataset.empty:
        print("没有可用样本")
        return 1

    normal_path = BASE / "data" / "overnight" / "wf_report_strict" / "summary.json"
    stress_path = BASE / "data" / "overnight" / "wf_report_strict_stress" / "summary.json"
    normal = _load_json(normal_path)
    stress = _load_json(stress_path)
    normal_window_path = normal_path.parent / "window_stats.csv"
    passed = _gate_passed(
        normal,
        stress,
        str(metadata.get("dataset_sha256", "")),
        normal_report_sha256=_sha256(normal_path) if normal_path.exists() else "",
        normal_window_sha256=(
            _sha256(normal_window_path) if normal_window_path.exists() else ""
        ),
    )
    if not args.force and not passed:
        print("拒绝训练最终模型: 严格Walk-Forward或冻结策略压力测试未通过")
        return 2

    try:
        model, policy, diagnostics, fit_rows = fit_final_model_and_policy(
            dataset,
            DEFAULT_SPEC,
            model_kind=args.model,
            require_strict=not args.force or args.dataset_mode == "strict",
        )
    except ValueError as exc:
        print(f"拒绝训练最终模型: {exc}")
        return 2

    production_dir = BASE / "data" / "overnight" / "model"
    model_dir = production_dir / "diagnostic" if args.force else production_dir
    model_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".json" if model.name == "ridge" else ".pkl"
    model_path = model_dir / f"overnight_{model.name}{suffix}"
    model_temporary = model_path.with_suffix(model_path.suffix + ".tmp")
    model.save(model_temporary)
    model_temporary.replace(model_path)

    importance_path = model_dir / "feature_importance.csv"
    importance_temporary = importance_path.with_suffix(".csv.tmp")
    model.feature_importance().to_csv(importance_temporary, index=False)
    importance_temporary.replace(importance_path)

    policy_value = policy.to_dict()
    policy_value.update(
        {
            "contract_version": "v4-selection-policy-v1",
            "feature_columns": FEATURE_COLUMNS,
            "diagnostics": diagnostics,
        }
    )
    policy_path = model_dir / "selection_policy.json"
    _write_json_atomic(policy_value, policy_path)

    feature_schema_hash = hashlib.sha256(
        json.dumps(FEATURE_COLUMNS, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    training_info = {
        "contract_version": "v4-model-training-v1",
        "model": model.name,
        "rows": int(len(fit_rows)),
        "start_date": str(fit_rows["date"].min())[:10],
        "end_date": str(fit_rows["date"].max())[:10],
        "dataset_mode": metadata.get("dataset_mode"),
        "dataset_path": str(selected_cache),
        "dataset_sha256": metadata.get("dataset_sha256", ""),
        "feature_columns": FEATURE_COLUMNS,
        "feature_schema_sha256": feature_schema_hash,
        "strict_dataset_ready": bool(metadata.get("strict_dataset_ready", False)),
        "point_in_time_universe_verified": bool(
            metadata.get("point_in_time_universe_verified", False)
        ),
        "point_in_time_security_name_verified": bool(
            metadata.get("point_in_time_security_name_verified", False)
        ),
        "forced_diagnostic": bool(args.force),
        "research_only": bool(args.force or not passed),
        "trained_at": now,
        "validation": diagnostics,
        "normal_report_sha256": _sha256(normal_path) if normal_path.exists() else "",
        "stress_report_sha256": _sha256(stress_path) if stress_path.exists() else "",
    }
    training_path = model_dir / "training_info.json"
    _write_json_atomic(training_info, training_path)

    if not args.force:
        manifest = {
            "contract_version": "v4-published-model-v1",
            "published_at": now,
            "model": model.name,
            "model_file": model_path.name,
            "model_sha256": _sha256(model_path),
            "policy_file": policy_path.name,
            "policy_sha256": _sha256(policy_path),
            "training_info_file": training_path.name,
            "training_info_sha256": _sha256(training_path),
            "dataset_sha256": metadata.get("dataset_sha256", ""),
            "feature_schema_sha256": feature_schema_hash,
        }
        _write_json_atomic(manifest, production_dir / "published_model.json")

    print(json.dumps(training_info, ensure_ascii=False, indent=2))
    print(f"模型: {model_path}")
    print(f"策略: {policy_path}")
    if args.force:
        print("[诊断隔离] --force产物为research_only，未写入生产发布清单")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
