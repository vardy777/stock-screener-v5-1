from types import SimpleNamespace
from v5.clock_gate import check

def runner(outputs):
 def run(command,timeout):return SimpleNamespace(returncode=0,stdout=outputs[tuple(command[:2])])
 return run

def test_clock_gate_requires_running_synced_service_and_measured_offset():
 outputs={("sc.exe","query"):"STATE : 4 RUNNING",("w32tm.exe","/query"):"Source: ntp.aliyun.com",("w32tm.exe","/stripchart"):"+0.002s\n-0.003s\n+0.001s"}
 result=check(runner=runner(outputs));assert result["passed"] and result["maximum_absolute_offset_seconds"]==.003
 outputs[("w32tm.exe","/stripchart")]="+0.8s\n+0.7s\n+0.9s";assert not check(runner=runner(outputs))["passed"]
 outputs[("w32tm.exe","/stripchart")]="+0.1s";assert not check(runner=runner(outputs))["passed"]
