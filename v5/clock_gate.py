"""V5-native causal Windows/NTP clock gate."""
from __future__ import annotations
import locale,re,subprocess

def check(*,runner=None,maximum_offset_seconds=.5):
    encoding=locale.getpreferredencoding(False) or "utf-8"
    def default(command,timeout):return subprocess.run(command,capture_output=True,text=True,encoding=encoding,errors="replace",timeout=timeout)
    runner=runner or default
    try:
        service=runner(["sc.exe","query","W32Time"],10);status=runner(["w32tm.exe","/query","/status"],10);strip=runner(["w32tm.exe","/stripchart","/computer:ntp.aliyun.com","/dataonly","/samples:3"],20)
    except (OSError,subprocess.SubprocessError) as exc:return {"passed":False,"reason":"TIME_QUERY_FAILED","error":f"{type(exc).__name__}: {exc}"}
    running=service.returncode==0 and "RUNNING" in service.stdout;synchronized=status.returncode==0 and "Local CMOS Clock" not in status.stdout
    offsets=[(-1 if sign=="-" else 1)*float(value) for sign,value in re.findall(r"([+-])\s*(\d+(?:\.\d+)?)s",strip.stdout)]
    maximum=max((abs(value) for value in offsets),default=None);verified=strip.returncode==0 and len(offsets)>=2 and maximum is not None and maximum<=maximum_offset_seconds
    passed=running and synchronized and verified
    return {"schema_version":"v5-clock-gate-v1","passed":passed,"service_running":running,"synchronized":synchronized,"offset_verified":verified,"maximum_absolute_offset_seconds":maximum,"sample_count":len(offsets),"reason":"OK" if passed else ("WINDOWS_TIME_OFFSET_TOO_LARGE" if running and synchronized else "WINDOWS_TIME_NOT_SYNCHRONIZED")}
