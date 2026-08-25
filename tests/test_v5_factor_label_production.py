import hashlib,json
from datetime import datetime
from v5.core import CHINA_TZ,ContractViolation
from v5.factor_label_production import produce,_label
from v5.opportunity import _order_snapshot
from v5.paper import PaperLedger,PaperEngine,PaperOrderV1

def _save_diagnostic(root):
    value={"schema_version":"v5-factor-diagnostics-v2","trade_date":"2026-08-25","created_at":"2026-08-25T09:25:20+08:00","snapshot_id":"ms1-morning","cohort":"full_eligible_09_25_cross_section","strict_labels_joined":False,"observations":[{"code":"000001","snapshot_id":"ms1-morning","observed_at":"2026-08-25T09:25:10+08:00","intraday_change":.01,"amount":10_000_000,"amount_percentile":.5,"close_location":.5}]}
    entity_id="fac1-"+hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:24];path=root/"factor_diagnostics/2026-08-25"/f"{entity_id}.json";path.parent.mkdir(parents=True);path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")),encoding="utf-8")

def test_no_strict_exit_legally_persists_insufficient_labelled_cohort(tmp_path):
    _save_diagnostic(tmp_path);result=produce(tmp_path,"2026-08-25",as_of="2026-08-26T10:00:00+08:00")
    assert result["label_status"]=="INSUFFICIENT_STRICT_LABELS" and result["rows"]==[] and result["cohort_id"].startswith("flcohort1-")

def test_non_0930_sell_event_cannot_become_strict_factor_label():
    trip={"code":"000001","buy_trade_date":"2026-08-25","buy_event_id":"buy","sell_event_id":"sell","return_basis":"net_pnl_divided_by_invested_capital","net_return":.01};pair={"recorded_at":"2026-08-26T09:31:00+08:00","buy_execution_snapshot_id":"buy-snap","sell_execution_snapshot_id":"sell-snap"}
    try:_label("baseline",trip,pair,"morning-snap")
    except ContractViolation as exc:assert "sell window" in str(exc)
    else:raise AssertionError("non-09:30 event must not become a strict label")

def test_tampered_paper_order_is_rejected_by_label_lineage_reader(tmp_path):
    ledger=PaperLedger(tmp_path/"paper");engine=PaperEngine(ledger);buy_at=datetime(2026,8,25,14,50,10,tzinfo=CHINA_TZ);sell_at=datetime(2026,8,26,9,30,10,tzinfo=CHINA_TZ)
    buy=PaperOrderV1("decision","BUY","000001","2026-08-25",buy_at.isoformat(),"10",100,"buy-snap","2026-08-26");buy_event=engine.execute(buy,at=buy_at)
    sell=PaperOrderV1("decision","SELL","000001","2026-08-26",sell_at.isoformat(),"10",100,"sell-snap","2026-08-26");engine.execute(sell,at=sell_at)
    path=tmp_path/"paper/orders/2026-08-25"/f"{buy.order_id}.json";raw=json.loads(path.read_text(encoding="utf-8"));raw["snapshot_id"]="forged";path.write_text(json.dumps(raw),encoding="utf-8")
    try:_order_snapshot(ledger,buy_event.event_id)
    except ContractViolation as exc:assert "content-address" in str(exc)
    else:raise AssertionError("tampered paper order must be rejected")
