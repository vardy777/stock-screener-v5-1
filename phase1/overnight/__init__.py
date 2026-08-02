"""Point-in-time overnight strategy research package."""

from .dataset import FEATURE_COLUMNS, build_dataset, load_or_build_dataset
from .backtesting import (
    build_precision_coverage_report,
    run_rule_backtest,
    run_walk_forward,
)
from .execution_labels import build_execution_labels, save_execution_labels
from .live_features import (
    build_live_feature_context,
    compute_live_features,
    save_live_feature_context,
    save_signal_features,
)
from .archive_refresh import merge_archive, validate_archive

__all__ = [
    "FEATURE_COLUMNS",
    "build_dataset",
    "load_or_build_dataset",
    "build_precision_coverage_report",
    "run_rule_backtest",
    "run_walk_forward",
    "build_execution_labels",
    "save_execution_labels",
    "build_live_feature_context",
    "merge_archive",
    "validate_archive",
    "compute_live_features",
    "save_live_feature_context",
    "save_signal_features",
]
