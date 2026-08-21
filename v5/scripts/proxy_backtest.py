from pathlib import Path
import argparse, json, os, sys

ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from v5.proxy_backtest import load_hourly_directory, run_proxy

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Research-only V5 hourly historical proxy; never strict evidence")
    parser.add_argument("--source", type=Path, default=ROOT / "phase1/data/daily")
    parser.add_argument("--sessions", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(); report = run_proxy(load_hourly_directory(args.source), lookback=args.sessions)
    raw = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True); tmp = args.output.with_suffix(f".{os.getpid()}.tmp"); tmp.write_text(raw, encoding="utf-8"); os.replace(tmp, args.output)
    print(raw)
