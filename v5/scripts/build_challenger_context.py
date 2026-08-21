from pathlib import Path
import argparse, json, sys

ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from v5.challenger_context import build_context, save_context
from v5.jobs import load_universe
from v5.paper_production import load_snapshot

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--target-trade-date", required=True); parser.add_argument("--previous-session", required=True); parser.add_argument("--reference-snapshot", type=Path, required=True); parser.add_argument("--workers", type=int, default=12); args = parser.parse_args()
    data = ROOT / "v5/data"; universe = load_universe(data, args.previous_session, require_native=True); snapshot = load_snapshot(args.reference_snapshot); references = {quote.code: quote.last_price for quote in snapshot.quotes}
    context = build_context(universe.codes, args.target_trade_date, args.previous_session, reference_prices=references, workers=args.workers, cache_dir=data / "challengers/volume_price_v1/context_cache" / args.previous_session); path = save_context(data, context)
    print(json.dumps({key: context[key] for key in ("context_id", "target_trade_date", "expected_previous_session", "universe_count", "valid_context_rows", "coverage", "reference_comparable_ratio", "reference_match_rate", "challenger_context_ready", "capture_duration_seconds")} | {"path": str(path)}, ensure_ascii=False, indent=2)); raise SystemExit(0 if context["challenger_context_ready"] else 3)
