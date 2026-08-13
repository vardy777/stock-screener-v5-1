from v5.dashboard import render
from v5.product_read_model import build
def test_v5_dashboard_is_one_page_decision_product_and_has_responsive_contract():
    page=render(build())
    for text in ("今天的结论","现在该做什么","今日推荐与执行规则","模拟账户与策略证据","全市场覆盖","全市场状态","数据时间","research_locked"):assert text in page
    assert "@media(max-width:760px)" in page and "@media(max-width:420px)" in page
    assert "严格模拟往返" in page and "可比基线日" in page
    assert "市场状态尚未生成，不能判断风险" in page and "当前未触发市场风险阻断" not in page
    assert "width:min(1160px,calc(100% - 32px))" in page and "<nav" not in page and "不连接券商" in page
