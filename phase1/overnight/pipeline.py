"""Label-aware construction and loading of proxy and strict datasets."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from market_universe import list_universe_codes
from strategy_spec import DEFAULT_SPEC, StrategySpec

from .dataset import build_dataset, load_or_build_dataset, save_dataset
from .execution_labels import build_execution_labels, save_execution_labels


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rebuild_labeled_datasets(
    daily_dir: Path,
    mixed_path: Path,
    *,
    strict_path: Optional[Path] = None,
    snapshot_root: Optional[Path] = None,
    calendar_path: Optional[Path] = None,
    spec: StrategySpec = DEFAULT_SPEC,
    max_stocks: Optional[int] = None,
) -> Tuple[pd.DataFrame, dict, pd.DataFrame, dict]:
    """Rebuild both datasets from the same audited execution-label source."""

    daily_dir = Path(daily_dir)
    mixed_path = Path(mixed_path)
    strict_path = Path(strict_path or mixed_path.with_name("strict_dataset.csv.gz"))
    snapshot_root = Path(
        snapshot_root or daily_dir.parent / "execution_snapshots" / "strict"
    )
    calendar_path = Path(
        calendar_path or daily_dir.parent / "trading_calendar_cn.csv"
    )
    universe = list_universe_codes(daily_dir, maximum=max_stocks)
    labels, label_metadata = build_execution_labels(
        snapshot_root,
        spec,
        universe_codes=universe,
        calendar_path=calendar_path,
    )
    label_path = mixed_path.parent / "execution_labels.csv.gz"
    save_execution_labels(labels, label_metadata, label_path)
    mixed, metadata = build_dataset(
        daily_dir,
        spec,
        max_stocks=max_stocks,
        execution_labels=labels,
        execution_metadata=label_metadata,
    )
    if mixed.empty:
        columns = list(mixed.columns)
        for column in ("date", "code", "net_return", "strict_row"):
            if column not in columns:
                columns.append(column)
        invalid = pd.DataFrame(columns=columns)
        invalid_metadata = dict(metadata)
        invalid_metadata.update(
            {
                "dataset_mode": "mixed_proxy_and_strict",
                "rows": 0,
                "strict_rows": 0,
                "strict_dataset_ready": False,
            }
        )
        invalid_metadata = save_dataset(invalid, invalid_metadata, mixed_path)
        strict_metadata = dict(invalid_metadata)
        strict_metadata.update(
            {
                "dataset_mode": "strict",
                "proxy_rows": 0,
                "strict_dataset_ready": False,
            }
        )
        strict_metadata = save_dataset(invalid, strict_metadata, strict_path)
        return invalid, invalid_metadata, invalid.copy(), strict_metadata
    metadata["dataset_mode"] = "mixed_proxy_and_strict"
    metadata = save_dataset(mixed, metadata, mixed_path)

    strict = mixed[mixed["strict_row"].fillna(False).astype(bool)].copy()
    strict_metadata = dict(metadata)
    strict_metadata.update(
        {
            "dataset_mode": "strict",
            "source_mixed_rows": int(len(mixed)),
            "rows": int(len(strict)),
            "strict_rows": int(len(strict)),
            "proxy_rows": 0,
            "strict_1450_rows": int(len(strict)),
            "strict_sell_rows": int(len(strict)),
            "strict_feature_rows": int(len(strict)),
            "strict_dataset_ready": bool(
                len(strict) > 0 and label_metadata.get("strict_dataset_ready", False)
            ),
            "start_date": str(strict["date"].min())[:10] if not strict.empty else "",
            "end_date": str(strict["date"].max())[:10] if not strict.empty else "",
            "execution_modes": (
                {str(key): int(value) for key, value in strict["execution_mode"].value_counts().items()}
                if not strict.empty else {}
            ),
        }
    )
    strict_metadata = save_dataset(strict, strict_metadata, strict_path)
    return mixed, metadata, strict, strict_metadata


def load_research_dataset(
    daily_dir: Path,
    cache_path: Path,
    *,
    dataset_mode: str = "proxy",
    rebuild: bool = False,
    max_stocks: Optional[int] = None,
    spec: StrategySpec = DEFAULT_SPEC,
) -> Tuple[pd.DataFrame, dict, Path]:
    if dataset_mode not in {"proxy", "strict"}:
        raise ValueError("dataset_mode must be proxy or strict")
    mixed_path = Path(cache_path)
    selected_path = (
        mixed_path.with_name("strict_dataset.csv.gz")
        if dataset_mode == "strict" and mixed_path.name == "dataset.csv.gz"
        else mixed_path
    )
    if rebuild:
        rebuild_labeled_datasets(
            daily_dir,
            mixed_path,
            spec=spec,
            max_stocks=max_stocks,
        )
    dataset, metadata = load_or_build_dataset(
        daily_dir,
        selected_path,
        spec,
        rebuild=False,
        max_stocks=max_stocks,
    )
    expected = str(metadata.get("dataset_sha256", ""))
    actual = _sha256(selected_path) if expected else ""
    metadata = dict(metadata)
    metadata["lineage_verified"] = bool(expected and actual == expected)
    if dataset_mode == "strict":
        if metadata.get("dataset_mode") != "strict":
            raise ValueError("严格回测拒绝非strict数据集")
        if not metadata["lineage_verified"]:
            raise ValueError("严格数据集哈希缺失或不匹配")
    return dataset, metadata, selected_path
