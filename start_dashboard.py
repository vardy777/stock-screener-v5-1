"""Standalone V4 dashboard launcher on port 8898."""
import json
import os
import subprocess
import sys
import time
import urllib.request

SCRIPT_DIR = r"C:\Users\lisha\stock-screener"
PYTHON_CANDIDATES = [
    os.path.join(SCRIPT_DIR, ".venv", "Scripts", "python.exe"),
]


def choose_python() -> str:
    for candidate in PYTHON_CANDIDATES:
        if not candidate or not os.path.exists(candidate):
            continue
        try:
            check = subprocess.run(
                [candidate, "-c", "import pandas"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
            if check.returncode == 0:
                return candidate
        except (OSError, subprocess.SubprocessError):
            continue
    raise RuntimeError("没有找到包含 pandas 的可用 Python 运行环境")


try:
    urllib.request.urlopen("http://127.0.0.1:8898/api/read-model", timeout=1)
    print("看板已经运行 → http://localhost:8898")
    raise SystemExit(0)
except OSError:
    pass

PYTHON = choose_python()

# 使用 Popen 并立即断开父子关系
with open(os.path.join(SCRIPT_DIR, "v4", "dashboard.log"), "w") as log:
    log.write(f"=== Dashboard started at {time.ctime()} ===\n")

creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
proc = subprocess.Popen(
    [PYTHON, "-X", "utf8", "-m", "v4.p5_dashboard", "--port", "8898", "--data-dir", "v4/data"],
    cwd=SCRIPT_DIR,
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    close_fds=True,
    creationflags=creationflags,
    env={**os.environ, "PYTHONUTF8": "1"},
)

print(f"Dashboard PID: {proc.pid}")
time.sleep(3)

# 验证（独立于子进程）
try:
    resp = urllib.request.urlopen("http://127.0.0.1:8898/api/read-model", timeout=5)
    d = json.loads(resp.read())
    print("看板运行正常 -> http://localhost:8898")
    print(f"   读模型时间: {d.get('generated_at','?')}")
except Exception as e:
    print(f"启动失败: {e}")
    raise SystemExit(1)
