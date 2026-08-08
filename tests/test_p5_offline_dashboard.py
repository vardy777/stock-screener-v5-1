import ast,json,tempfile,threading,unittest,urllib.error,urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from v4.execution import CHINA_TZ
from v4.p5_dashboard import Handler,frozen_demo_model,render
from v4.p5_read_model import DashboardContractViolation,DashboardReadModelBuilder

ROOT=Path(__file__).resolve().parents[1]

class P5OfflineDashboardTests(unittest.TestCase):
    def test_frozen_demo_read_model_is_deterministic_and_cohorts_are_separate(self):
        first=frozen_demo_model(); second=frozen_demo_model(); self.assertEqual(first,second)
        self.assertTrue(first.read_model_id.startswith("drm1-")); self.assertTrue(first.evidence["cohorts_separated"])
        self.assertEqual(first.evidence["strict"]["pairs"],0); self.assertEqual(first.evidence["paper"]["round_trips"],3)
        self.assertEqual(first.account["closed_trades"],3); self.assertAlmostEqual(first.account["win_rate"],2/3)

    def test_missing_sources_degrade_explicitly_and_naive_time_fails_closed(self):
        builder=DashboardReadModelBuilder()
        with self.assertRaisesRegex(DashboardContractViolation,"timezone"):
            builder.build(generated_at=datetime(2026,8,8),production_status="research_locked")
        model=builder.build(generated_at=datetime(2026,8,8,tzinfo=CHINA_TZ),production_status="research_locked")
        self.assertEqual(model.data_status,"DEGRADED")
        codes={x["reason_code"] for x in model.issues}
        self.assertTrue({"MORNING_POOL_MISSING","CONFIRMATION_MISSING","MARKET_DATA_INVALID","HEARTBEAT_STALE"}.issubset(codes))
        self.assertIsNone(model.account["win_rate"])

    def test_html_has_required_control_center_sections_and_no_mutation_controls(self):
        page=render(frozen_demo_model())
        for text in ("今日不可变链路","09:25母池 → 14:50确认","市场状态","市场情绪（描述性）","证据分层","P4任务与SLA","视图不控制执行"):
            self.assertIn(text,page)
        for forbidden in ("运行买入","运行卖出","重置账户","api/run_buy","api/reset"):
            self.assertNotIn(forbidden,page)

    def test_http_surface_is_read_only_and_mode_chase_compatible(self):
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            base=f"http://127.0.0.1:{server.server_port}"
            self.assertIn("P5只读控制台",urllib.request.urlopen(base+"/?mode=chase").read().decode())
            payload=json.loads(urllib.request.urlopen(base+"/api/read-model").read().decode()); self.assertEqual(payload["schema_version"],"dashboard-read-model-v1")
            request=urllib.request.Request(base+"/api/reset",data=b"",method="POST")
            with self.assertRaises(urllib.error.HTTPError) as caught: urllib.request.urlopen(request)
            self.assertEqual(caught.exception.code,405)
        finally: server.shutdown();server.server_close()

    def test_p5_modules_are_read_only_and_existing_8898_does_not_import_them(self):
        forbidden={"v4.simulation","v4.push","v4.paper_scheduler","v4.market_gateway","data_fetcher"}; violations=[]
        for path in sorted((ROOT/"v4").glob("p5_*.py")):
            tree=ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules=[]
                if isinstance(node,ast.ImportFrom): modules.append(node.module or "")
                if isinstance(node,ast.Import): modules.extend(x.name for x in node.names)
                for module in modules:
                    if module in forbidden: violations.append(f"{path.name}:{node.lineno}:{module}")
        self.assertEqual(violations,[])
        self.assertNotIn("p5_",(ROOT/"v4"/"dashboard.py").read_text(encoding="utf-8"))

if __name__=="__main__": unittest.main()
