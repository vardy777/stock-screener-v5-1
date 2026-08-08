#!/usr/bin/env python3
"""Send one clearly labelled non-trading message to validate PushPlus."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from v4.push import send_wechat


def main() -> int:
    accepted = send_wechat(
        "V4 本地推送链路测试（非选股）",
        (
            "<h3>V4本地PushPlus测试</h3>"
            "<p>此消息只验证项目.venv、v4/.env和PushPlus，"
            "不是股票建议，也不会触发交易。</p>"
        ),
    )
    print(f"pushplus_accepted={str(bool(accepted)).lower()}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
