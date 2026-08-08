import ast,hashlib,json,tempfile,threading,unittest,urllib.error,urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from v4.execution import CHINA_TZ
from v4.p5_dashboard import Handler,frozen_demo_model,frozen_scenario,render
from v4.p5_read_model import DashboardContractViolation,DashboardReadModelBuilder
from v4.p5_sources import P5ReadOnlySources

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
        for text in ("今日不可变链路","09:25母池 → 14:50确认","市场状态","市场情绪（描述性）","证据分层","板块资金流","模拟账户权益与回撤","已闭合隔夜往返","来源与哈希","P4任务与SLA","视图不控制执行"):
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

    def test_real_file_adapter_is_read_only_and_hashes_every_source(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"candidate_journal").mkdir()
            files={
                root/"candidate_journal"/"2026-08-08.json":{"trade_date":"2026-08-08","morning":{"pool_id":"mp1","candidates":[{"code":"000001","rank":1,"score":80}]},"confirmation":{"decision_id":"cd1","outcome":"BLOCKED","candidates":[]}},
                root/"market_context.json":{"generated_at":"2026-08-08T14:50:00+08:00","market_state":{"data_valid":True,"snapshot_id":"ms1","rise_count":2,"fall_count":1,"fresh_quote_coverage":1}},
                root/"sector_fund_flow.json":{"time":"2026-08-08T14:50:00+08:00","sector_flows":{"银行":{"net_inflow":1.2,"change_pct":.5}}},
            }
            for path,value in files.items(): path.write_text(json.dumps(value,ensure_ascii=False),encoding="utf-8")
            before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
            model=P5ReadOnlySources(root).build(generated_at=datetime(2026,8,8,15,tzinfo=CHINA_TZ),operations={"heartbeat":{"status":"ALIVE"}})
            after={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
            self.assertEqual(before,after); self.assertEqual(len(model.sources),3)
            self.assertTrue(all(x["status"]=="VALID" and len(x["sha256"])==64 for x in model.sources))
            self.assertEqual(model.candidates[0]["code"],"000001")

    def test_corrupt_and_missing_sources_fail_visibly_without_fabricated_values(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"candidate_journal").mkdir()
            (root/"market_context.json").write_text("{bad",encoding="utf-8")
            model=P5ReadOnlySources(root).build(generated_at=datetime(2026,8,8,15,tzinfo=CHINA_TZ))
            self.assertEqual(model.data_status,"DEGRADED")
            self.assertEqual(model.market["turnover_yi"],0)
            self.assertEqual(model.fund_flow["status"],"unavailable")
            statuses={x["status"] for x in model.sources}; self.assertTrue({"MISSING","INVALID"}.issubset(statuses))
            self.assertIn("SOURCE_INVALID",{x["reason_code"] for x in model.issues})

    def test_legacy_business_files_without_entity_ids_are_not_marked_done(self):
        model=DashboardReadModelBuilder().build(generated_at=datetime(2026,8,8,15,tzinfo=CHINA_TZ),production_status="research_locked",
            morning={"candidates":[]},confirmation={"candidates":[]},market={"data_valid":True},fund_flow={"status":"valid"},heartbeat={"status":"ALIVE"})
        states={x["key"]:x["status"] for x in model.timeline}
        self.assertEqual(states["morning"],"INVALID_ENTITY"); self.assertEqual(states["confirmation"],"INVALID_ENTITY")
        codes={x["reason_code"] for x in model.issues}; self.assertTrue({"MORNING_ENTITY_ID_MISSING","DECISION_ENTITY_ID_MISSING"}.issubset(codes))

    def test_blocked_unknown_failed_task_and_empty_account_scenarios_are_explicit(self):
        builder=DashboardReadModelBuilder(); now=datetime(2026,8,8,15,tzinfo=CHINA_TZ)
        base={"generated_at":now,"production_status":"research_locked","morning":{"pool_id":"p","candidates":[]},
              "market":{"data_valid":True},"fund_flow":{"status":"valid"},"heartbeat":{"status":"ALIVE"}}
        blocked=builder.build(**base,confirmation={"decision_id":"d","outcome":"BLOCKED"})
        unknown=builder.build(**base,confirmation={"decision_id":"d","outcome":"OUTCOME_UNKNOWN"},task_receipts=[{"status":"OUTCOME_UNKNOWN"}])
        self.assertIn("DECISION_BLOCKED",{x["reason_code"] for x in blocked.issues})
        self.assertTrue({"OUTCOME_UNKNOWN","TASK_FAILURE"}.issubset({x["reason_code"] for x in unknown.issues}))
        self.assertIsNone(unknown.account["win_rate"]); self.assertIn("尚无已闭合往返",render(unknown))

    def test_all_frozen_visual_scenarios_render_without_mutation_controls(self):
        expected={"missing":"MORNING_POOL_MISSING","outcome_unknown":"OUTCOME_UNKNOWN","task_failed":"TASK_FAILURE","no_trades":"MODEL_UNPUBLISHED"}
        for name,code in expected.items():
            with self.subTest(name=name):
                model=frozen_scenario(name); page=render(model)
                self.assertIn(code,{x["reason_code"] for x in model.issues})
                self.assertIn("P5只读控制台",page); self.assertNotIn("<button",page); self.assertNotIn("<form",page)

if __name__=="__main__": unittest.main()
