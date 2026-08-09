import json,tempfile,unittest
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from v4.p5_components import render_acceptance_panels
from v4.p5_sources import P5ReadOnlySources

class P5RealAdapterTests(unittest.TestCase):
    def write(self,root,relative,value):
        path=root/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value),encoding="utf-8")
    def test_optional_real_artifacts_are_projected_without_writes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            self.write(root,"acceptance/live_window_acceptance.json",{"passed":False,"checks":[{"name":"morning_0925","passed":True}]})
            self.write(root,"acceptance/cutover_readiness.json",{"ready":False,"apply_allowed":False,"plan_id":"cut-test"})
            self.write(root,"research/strict_model_admission.json",{"passed":False,"sample_count":0,"reasons":["INSUFFICIENT_STRICT_SAMPLES"]})
            before={p:p.read_bytes() for p in root.rglob("*.json")}
            model=P5ReadOnlySources(root).build(generated_at=datetime(2026,8,10,tzinfo=ZoneInfo("Asia/Shanghai")))
            self.assertEqual(model.evidence["live_windows"][0]["status"],"PASSED")
            self.assertFalse(model.evidence["strict_admission"]["passed"])
            self.assertEqual(model.operations["cutover"]["plan_id"],"cut-test")
            self.assertEqual(before,{p:p.read_bytes() for p in root.rglob("*.json")})
    def test_components_are_separate_and_escaped(self):
        body=render_acceptance_panels({"evidence":{"live_windows":[],"strict_admission":{"reasons":["<blocked>"]}},"operations":{"cutover":{}}})
        for name in ("live-window-acceptance","strict-sample-admission","cutover-readiness"): self.assertIn(f"data-component='{name}'",body)
        self.assertIn("&lt;blocked&gt;",body); self.assertNotIn("<blocked>",body)
if __name__=="__main__": unittest.main()
