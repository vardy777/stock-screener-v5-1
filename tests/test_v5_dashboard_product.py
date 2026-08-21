from v5.dashboard import render
from v5.product_read_model import build
from v5.contracts import AcquisitionSessionV1
from datetime import datetime
from v5.core import CHINA_TZ
def test_v5_dashboard_is_one_page_decision_product_and_has_responsive_contract():
    page=render(build())
    for text in ("今天的结论","现在该做什么","今日推荐与执行规则","模拟账户与策略证据","全市场覆盖","沪深市场状态","含科创板，暂不含北交所","数据时间","research_locked"):assert text in page
    assert "@media(max-width:760px)" in page and "@media(max-width:420px)" in page
    assert "严格模拟往返" in page and "可比基线日" in page
    assert "市场状态尚未生成，不能判断风险" in page and "当前未触发市场风险阻断" not in page
    assert "width:min(1160px,calc(100% - 32px))" in page and "<nav" not in page and "不连接券商" in page
    assert "V5 ONLY · V5-20260821-CHALLENGER" in page and "http-equiv='refresh' content='30'" in page
    assert "两条研究线并行对照" in page and "量价挑战者" in page
    assert "唯一PushPlus推荐" in page and "不发送PushPlus" not in page

def test_dashboard_marks_challenger_as_shadow_and_keeps_baseline_as_only_push_source():
    model=build();model.validation["challenger"]={"stage":"morning","candidate_count":1,"context_ready":True,"candidates":[{"name":"测试股","code":"000001","change_pct":2.1,"reasons":["量价结构通过"],"risks":["隔夜跳空"]}],"account":{"cash":90000,"positions":[]},"performance":{"trade_count":2,"net_pnl":123.45}}
    page=render(model)
    assert "量价挑战者 · 影子研究线" in page and "不发送PushPlus" in page
    assert "这是09:25和14:50 PushPlus的唯一内容来源" in page

def test_dashboard_keeps_baseline_visible_when_challenger_projection_failed():
    model=build();model.validation["challenger"]={"status":"FAILED","error_type":"ContractViolation"}
    page=render(model)
    assert "挑战者数据不可用" in page and "基线仍可正常运行和展示" in page

def test_rejected_acquisition_remains_visible_as_source_diagnostics():
    acquisition=AcquisitionSessionV1.build(trade_date="2026-08-17",stage="morning",requested_at=datetime(2026,8,17,9,25,5,tzinfo=CHINA_TZ),expected_codes=5212,selected_snapshot_id="",accepted=False,source_attempts=[{"source":"sina","coverage":.94,"complete":False},{"source":"tencent","coverage":.99,"complete":False}])
    model=build(acquisition=acquisition)
    page=render(model)
    assert model.today["data_quality"]=="rejected" and model.today["coverage"]==.99
    assert "新浪" not in page and "tencent：99.00%（未通过）" in page

def test_orphan_signal_quality_explains_valid_data_but_forces_empty_position():
    model=build();model.today.update({"data_quality":"accepted_no_morning_pool","action":"14:49严格行情已冻结，但缺少09:25母池：今日不确认、不模拟买入"})
    page=render(model)
    assert "严格尾盘行情有效，但今天缺少09:25母池；保持空仓，不确认、不模拟买入" in page
    assert "value warn'>accepted_no_morning_pool" in page
