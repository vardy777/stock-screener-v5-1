from datetime import date, timedelta
import json
from v5.challenger_context import build_symbol_context, build_context, load_context, save_context


def rows(end=date(2026, 8, 21), count=30):
    result=[]
    for offset in range(count):
        day=end-timedelta(days=count-1-offset); price=10+offset*.1
        result.append([day.isoformat(),str(price),str(price+.05),str(price+.1),str(price-.1),str(10000+offset*100)])
    return result


def test_context_discards_future_and_builds_causal_5_10_day_features():
    source=rows()+[["2026-08-24","99","99","99","99","1"]];value,reason,future=build_symbol_context(source,"000001","2026-08-21")
    assert reason=="ok" and future==1 and value["context_date"]=="2026-08-21" and value["ret_5d"]>0 and value["volume_ratio_5_10"]>1


def test_context_gate_is_content_addressed_and_requires_95_percent(tmp_path):
    codes=[f"{index:06d}" for index in range(1,21)];references={code:12.9 for code in codes}
    context=build_context(codes,"2026-08-24","2026-08-21",reference_prices=references,workers=2,fetcher=lambda _:rows())
    assert context["challenger_context_ready"] and context["strict_sample"] is False
    path=save_context(tmp_path,context);assert path.exists() and load_context(tmp_path,"2026-08-24")["context_id"]==context["context_id"]
    raw=json.loads(path.read_text());raw["coverage"]=0;path.write_text(json.dumps(raw),encoding="utf-8")
    try:load_context(tmp_path,"2026-08-24")
    except Exception as exc:assert "invalid" in str(exc)
    else:raise AssertionError("tampered challenger context accepted")
