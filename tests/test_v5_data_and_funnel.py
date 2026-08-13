import unittest
import threading,time
from datetime import datetime,timedelta
from types import SimpleNamespace
from v5.core import CHINA_TZ
from v5.market_snapshot import MarketSnapshotV1,QuoteV1
from v5.eastmoney_source import EastmoneyRealtimeSource
from v5.contracts import AcquisitionSessionV1
from v5.data_production import MultiSourceAcquirer,ConsensusAcquirer
from v5.universe import UniverseV1
from v5.funnel import CandidateFunnel,FunnelPolicyV1
from v5.storage import V5FactStore
from v5.decision_flow import MorningPoolV5,ConfirmationV5
from v5.performance import report_strict_paper
from v5.product_read_model import build as build_product
from v5.dashboard import render
from tempfile import TemporaryDirectory
from pathlib import Path

NOW=datetime(2026,8,13,14,49,30,tzinfo=CHINA_TZ)
def quote(code,**changes):
    row={"code":code,"name":"测试","trade_date":"2026-08-13","exchange_time":(NOW-timedelta(seconds=1)).isoformat(),"provider_time":(NOW-timedelta(seconds=1)).isoformat(),"received_at":NOW.isoformat(),"last_price":10.2,"previous_close":10.0,"open_price":10.0,"high_price":10.3,"low_price":9.9,"bid1":10.19,"bid1_volume":10000,"ask1":10.21,"ask1_volume":10000,"volume":100000,"amount":8_000_000,"halted":False,"limit_up":False,"limit_down":False,"provider":"test"};row.update(changes);return QuoteV1.from_mapping(row)
def snapshot(rows,expected=2):return MarketSnapshotV1.build(trade_date="2026-08-13",session="signal",batch_started_at=NOW-timedelta(seconds=2),batch_completed_at=NOW,quotes=rows,expected_codes=expected)
class Source:
    def __init__(self,name,value):self.name=name;self.value=value
    def capture(self,*args,**kwargs):
        if isinstance(self.value,Exception):raise self.value
        return self.value

class V5DataAndFunnelTests(unittest.TestCase):
    def test_universe_is_content_addressed_and_board_filtered(self):
        universe=UniverseV1.build(trade_date="2026-08-13",created_at=NOW,codes=["000001","600000","900901","430001"],sources=["daily_archive"])
        self.assertEqual(universe.codes,("000001","600000"));self.assertTrue(universe.universe_id.startswith("univ1-"))
        with TemporaryDirectory() as directory:self.assertEqual(universe.save(directory),universe.save(directory))
    def test_universe_identity_includes_date_time_and_source_lineage(self):
        first=UniverseV1.build(trade_date="2026-08-13",created_at=NOW,codes=["000001"],sources=["seed"]);second=UniverseV1.build(trade_date="2026-08-14",created_at=NOW+timedelta(days=1),codes=["000001"],sources=["live"]);self.assertNotEqual(first.universe_id,second.universe_id)

    def test_consensus_requires_both_complete_sources_and_matching_prices(self):
        universe=UniverseV1.build(trade_date="2026-08-13",created_at=NOW,codes=["000001","000002"],sources=["test"])
        left=snapshot([quote("000001"),quote("000002")]);right=snapshot([quote("000001"),quote("000002")])
        result=ConsensusAcquirer(Source("sina",left),Source("eastmoney",right)).acquire(universe,stage="signal",now=NOW)
        self.assertTrue(result.accepted);self.assertEqual(result.report["match_ratio"],1)
        conflict=snapshot([quote("000001",last_price=11),quote("000002")])
        rejected=ConsensusAcquirer(Source("sina",left),Source("eastmoney",conflict)).acquire(universe,stage="signal",now=NOW)
        self.assertFalse(rejected.accepted);self.assertEqual(rejected.report["price_conflicts"],1)

    def test_consensus_rejects_same_source_identity_even_with_two_objects(self):
        good=snapshot([quote("000001"),quote("000002")])
        with self.assertRaisesRegex(ValueError,"distinct source identities"):
            ConsensusAcquirer(Source("same",good),Source("same",good))

    def test_consensus_conflict_union_is_not_double_counted_and_latest_strict_snapshot_is_primary(self):
        universe=UniverseV1.build(trade_date="2026-08-13",created_at=NOW,codes=["000001","000002"],sources=["test"]);left=snapshot([quote("000001"),quote("000002")]);later_at=NOW+timedelta(seconds=1);later=MarketSnapshotV1.build(trade_date="2026-08-13",session="signal",batch_started_at=NOW-timedelta(seconds=1),batch_completed_at=later_at,quotes=[quote("000001"),quote("000002")],expected_codes=2);result=ConsensusAcquirer(Source("sina",left),Source("eastmoney",later)).acquire(universe,stage="signal",now=NOW);assert result.accepted and result.primary.snapshot_id==later.snapshot_id and result.report["selected_snapshot_id"]==later.snapshot_id

    def test_consensus_never_merges_two_incomplete_sources_to_inflate_coverage(self):
        universe=UniverseV1.build(trade_date="2026-08-13",created_at=NOW,codes=["000001","000002"],sources=["test"])
        result=ConsensusAcquirer(Source("one",snapshot([quote("000001")],2)),Source("two",snapshot([quote("000002")],2))).acquire(universe,stage="signal",now=NOW)
        self.assertFalse(result.accepted);self.assertIsNone(result.primary)
    def test_consensus_captures_independent_sources_concurrently_and_keeps_order(self):
        universe=UniverseV1.build(trade_date="2026-08-13",created_at=NOW,codes=["000001","000002"],sources=["test"]);barrier=threading.Barrier(2);good=snapshot([quote("000001"),quote("000002")])
        class ConcurrentSource:
            def __init__(self,name):self.name=name
            def capture(self,*args,**kwargs):barrier.wait(timeout=1);return good
        result=ConsensusAcquirer(ConcurrentSource("first"),ConcurrentSource("second")).acquire(universe,stage="signal",now=NOW)
        self.assertTrue(result.accepted);self.assertEqual([x["source"] for x in result.report["attempts"]],["first","second"])
    def test_eastmoney_source_maps_only_requested_codes_and_preserves_provider_time(self):
        epoch=int((NOW-timedelta(seconds=1)).timestamp())
        payload={"rc":0,"data":{"diff":[{"f12":"000001","f14":"平安银行","f2":10.2,"f5":1000,"f6":8000000,"f15":10.3,"f16":10.0,"f17":10.1,"f18":10.0,"f31":10.19,"f32":10.21,"f33":100,"f34":120,"f124":epoch},{"f12":"600000","f14":"浦发银行","f2":9.8,"f5":500,"f6":4000000,"f15":9.9,"f16":9.7,"f17":9.8,"f18":9.75,"f31":9.79,"f32":9.81,"f33":20,"f34":30,"f124":epoch}]}}
        source=EastmoneyRealtimeSource(fetch_json=lambda *_:payload,clock=lambda:NOW)
        result=source.capture(["000001"],stage="signal",now=NOW)
        self.assertEqual([q.code for q in result.quotes],["000001"]);self.assertEqual(result.quotes[0].provider,source.name)
        self.assertEqual(result.quotes[0].bid1_volume,10000);self.assertEqual(result.quotes[0].ask1_volume,12000);self.assertTrue(result.quality.accepted)

    def test_eastmoney_missing_timestamp_is_rejected_not_guessed(self):
        payload={"rc":0,"data":{"diff":[{"f12":"000001","f14":"平安银行","f2":10.2,"f5":1000,"f6":8000000,"f15":10.3,"f16":10.0,"f17":10.1,"f18":10.0,"f31":10.19,"f32":10.21,"f33":100,"f34":120,"f124":"-"}]}}
        result=EastmoneyRealtimeSource(fetch_json=lambda *_:payload,clock=lambda:NOW).capture(["000001"],stage="signal",now=NOW)
        self.assertEqual(result.quotes,());self.assertFalse(result.quality.accepted);self.assertIn("empty",result.quality.reasons)
    def test_eastmoney_source_fails_closed_when_overall_budget_is_exhausted(self):
        ticks=iter((0,2));source=EastmoneyRealtimeSource(fetch_json=lambda *_:{},overall_budget_seconds=1,monotonic=lambda:next(ticks),clock=lambda:NOW)
        with self.assertRaisesRegex(TimeoutError,"overall budget"):source.capture(["000001"],stage="signal",now=NOW)
    def test_eastmoney_honors_provider_reduced_page_size_beyond_twenty_pages(self):
        epoch=int((NOW-timedelta(seconds=1)).timestamp());codes=[f"{index:06d}" for index in range(1,22)]
        def fetch(url,timeout):
            from urllib.parse import parse_qs,urlparse
            page=int(parse_qs(urlparse(url).query)["pn"][0]);code=codes[page-1]
            row={"f12":code,"f14":"test","f2":10.2,"f5":1000,"f6":8000000,"f15":10.3,"f16":10.0,"f17":10.1,"f18":10.0,"f31":10.19,"f32":10.21,"f33":100,"f34":120,"f124":epoch}
            return {"rc":0,"data":{"total":len(codes),"diff":[row]}}
        result=EastmoneyRealtimeSource(fetch_json=fetch,clock=lambda:NOW,page_size=500,overall_budget_seconds=100).capture(codes,stage="signal",now=NOW)
        self.assertEqual(len(result.quotes),21);self.assertTrue(result.quality.accepted)
    def test_eastmoney_rejects_provider_repeated_page_instead_of_counting_duplicates(self):
        epoch=int((NOW-timedelta(seconds=1)).timestamp());row={"f12":"000001","f14":"test","f2":10.2,"f5":1000,"f6":8000000,"f15":10.3,"f16":10.0,"f17":10.1,"f18":10.0,"f31":10.19,"f32":10.21,"f33":100,"f34":120,"f124":epoch}
        source=EastmoneyRealtimeSource(fetch_json=lambda *_:{"rc":0,"data":{"total":2,"diff":[row]}},clock=lambda:NOW,overall_budget_seconds=100)
        with self.assertRaisesRegex(RuntimeError,"repeated page"):source.capture(["000001","000002"],stage="signal",now=NOW)
    def test_second_source_is_selected_only_when_strict_snapshot_is_accepted(self):
        bad=snapshot([quote("000001")],2);good=snapshot([quote("000001"),quote("000002")],2)
        result=MultiSourceAcquirer([Source("primary",bad),Source("backup",good)]).acquire(["000001","000002"],stage="signal",now=NOW)
        self.assertTrue(result.session.accepted);self.assertEqual(result.snapshot.snapshot_id,good.snapshot_id);self.assertEqual(len(result.session.source_attempts),2)
        self.assertFalse(result.session.source_attempts[0]["accepted"])
    def test_failed_sources_remain_auditable_and_never_lower_coverage_gate(self):
        bad=snapshot([quote("000001")],2)
        result=MultiSourceAcquirer([Source("broken",RuntimeError("down")),Source("thin",bad)]).acquire(["000001","000002"],stage="morning",now=NOW)
        self.assertFalse(result.session.accepted);self.assertIsNone(result.snapshot);self.assertEqual(result.session.source_attempts[0]["source"],"broken")
    def test_funnel_records_rejections_and_confirmation_is_mother_pool_subset(self):
        rows=[quote("000001"),quote("000002",amount=1),quote("000003",limit_up=True),quote("000004",last_price=10.5)]
        snap=snapshot(rows,4);funnel=CandidateFunnel(FunnelPolicyV1(min_amount=5_000_000,max_candidates=5))
        morning=funnel.run(snap,market_state_id="mstate1-test",market_valid=True,stage="morning")
        self.assertEqual([x["code"] for x in morning.candidates],["000004","000001"])
        self.assertEqual(morning.stages[1]["rejected"]["limit_locked"],1);self.assertEqual(morning.stages[2]["rejected"]["insufficient_amount"],1)
        confirm=funnel.run(snap,market_state_id="mstate1-test",market_valid=True,stage="confirmation",allowed_codes=["000001"])
        self.assertEqual([x["code"] for x in confirm.candidates],["000001"])
        self.assertEqual(confirm.stages[3]["rejected"]["outside_morning_pool"],1)
    def test_invalid_market_fails_closed_with_explained_empty_funnel(self):
        funnel=CandidateFunnel();result=funnel.run(snapshot([quote("000001"),quote("000002")]),market_state_id="mstate1-test",market_valid=False,stage="morning")
        self.assertFalse(result.accepted);self.assertEqual(result.candidates,());self.assertEqual(result.stages[3]["rejected"]["market_data_invalid"],2)
    def test_morning_observation_does_not_require_ask_but_confirmation_does(self):
        no_ask=snapshot([quote("000001",ask1=0,ask1_volume=0)],1);funnel=CandidateFunnel();morning=funnel.run(no_ask,market_state_id="mstate1-test",market_valid=True,stage="morning");assert [x["code"] for x in morning.candidates]==["000001"]
        confirmation=funnel.run(no_ask,market_state_id="mstate1-test",market_valid=True,stage="confirmation",allowed_codes=["000001"]);assert confirmation.candidates==() and confirmation.stages[1]["rejected"]["missing_buy_book"]==1
    def test_special_treatment_and_delisting_names_are_transparently_excluded(self):
        rows=[quote("000001",name="*ST测试"),quote("000002",name="退市测试"),quote("000003",name="正常股票")];result=CandidateFunnel().run(snapshot(rows,3),market_state_id="mstate1-test",market_valid=True,stage="morning");assert [x["code"] for x in result.candidates]==["000003"] and result.stages[1]["rejected"]["special_treatment"]==2
    def test_v5_facts_are_content_addressed_immutable(self):
        good=snapshot([quote("000001"),quote("000002")]);acq=MultiSourceAcquirer([Source("one",good)]).acquire(["000001","000002"],stage="signal",now=NOW)
        funnel=CandidateFunnel().run(good,market_state_id="mstate1-test",market_valid=True,stage="morning")
        with TemporaryDirectory() as directory:
            store=V5FactStore(Path(directory));first=store.save_session(acq.session);self.assertEqual(first,store.save_session(acq.session));second=store.save_funnel(funnel)
            self.assertTrue(first.exists());self.assertTrue(second.exists())
    def test_same_day_confirmation_has_mother_pool_subset_and_change_facts(self):
        morning_snap=snapshot([quote("000001"),quote("000002",last_price=10.1)])
        confirm_snap=snapshot([quote("000001",last_price=10.3),quote("000002",last_price=10.2)])
        funnel=CandidateFunnel();morning=funnel.run(morning_snap,market_state_id="mstate1-morning",market_valid=True,stage="morning")
        pool=MorningPoolV5.from_funnel(morning,created_at=NOW)
        confirm=funnel.run(confirm_snap,market_state_id="mstate1-confirm",market_valid=True,stage="confirmation",allowed_codes=["000001"])
        decision=ConfirmationV5.from_funnel(pool,confirm,decided_at=NOW)
        self.assertEqual(decision.morning_pool_id,pool.pool_id);self.assertEqual([x["code"] for x in decision.candidates],["000001"]);self.assertEqual(decision.changes[0]["morning_rank"],1)
    def test_performance_is_paper_only_and_fails_closed_for_small_sample(self):
        report=report_strict_paper([{"net_return":.01,"net_pnl":100},{"net_return":-.02,"net_pnl":-200}],baseline_returns=[0,.001],minimum_trades=40)
        self.assertEqual(report.cohort,"paper_round_trips");self.assertEqual(report.trade_count,2);self.assertEqual(report.conclusion,"INSUFFICIENT_EVIDENCE");self.assertEqual(report.win_rate,.5)
    def test_product_read_model_is_decision_first_and_honest_when_data_missing(self):
        model=build_product();self.assertIn("不交易",model.today["action"]);self.assertEqual(model.candidates["empty_reason"],"行情质量未通过");self.assertTrue(model.validation["research_locked"])
        page=render(model);self.assertIn("今天的结论",page);self.assertIn("今日推荐与执行规则",page);self.assertIn("模拟账户与策略证据",page);self.assertIn("证据不足，不能证明策略有效",page);self.assertNotIn("<button",page);self.assertNotIn("<nav",page)

    def test_product_read_model_projects_selected_snapshot_source_not_last_attempt(self):
        session=AcquisitionSessionV1.build(trade_date="2026-08-13",stage="morning",requested_at=NOW,expected_codes=2,selected_snapshot_id="ms1-selected",accepted=True,source_attempts=[{"source":"selected","snapshot_id":"ms1-selected","coverage":.97,"complete":True},{"source":"other","snapshot_id":"ms1-other","coverage":1.0,"complete":True}])
        today=build_product(acquisition=session).today;self.assertEqual(today["source"],"selected");self.assertEqual(today["coverage"],.97);self.assertEqual(today["source_consensus"],["selected","other"])

    def test_v5_runtime_has_no_direct_v4_imports(self):
        root=Path(__file__).resolve().parents[1]/"v5"
        violations=[]
        for path in root.glob("*.py"):
            text=path.read_text(encoding="utf-8")
            if "from v4" in text or "import v4" in text:violations.append(path.name)
        self.assertEqual(violations,[])
if __name__=="__main__":unittest.main()
