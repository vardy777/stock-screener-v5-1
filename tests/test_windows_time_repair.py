from pathlib import Path
import subprocess,unittest

ROOT=Path(__file__).resolve().parents[1]

class WindowsTimeRepairTests(unittest.TestCase):
    def test_script_parses_and_has_fail_closed_checks(self):
        path=ROOT/"scripts/repair_windows_time.ps1"
        text=path.read_text(encoding="utf-8")
        self.assertIn("Administrator privileges are required",text)
        self.assertIn("Windows Time status query failed",text)
        self.assertIn("Local CMOS Clock",text)
        result=subprocess.run(["powershell.exe","-NoProfile","-Command",
            f"$null=[scriptblock]::Create((Get-Content -Raw -LiteralPath '{path}')); exit 0"],
            capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)

if __name__=="__main__": unittest.main()
