"""Paired opportunity-day evidence for baseline versus a challenger."""
from __future__ import annotations
import json
from pathlib import Path

def _lineage(ledger):
    orders={}
    root=Path(ledger.root)/"orders"
    for path in root.glob("*/*.json") if root.exists() else ():
        row=json.loads(path.read_text(encoding="utf-8"));orders[row["order_id"]]=row.get("snapshot_id","")
    return {row["event_id"]:orders.get(row["event"]["order_id"],"") for row in ledger.events()}

def build_pairs(baseline_ledger,challenger_ledger,regimes=None,*,pairing_facts=None):
    if pairing_facts is not None:return [dict(row) for row in pairing_facts if row.get("eligible") is True]
    baseline=baseline_ledger.round_trips();challenger=challenger_ledger.round_trips();b={x["buy_trade_date"]:x for x in baseline};c={x["buy_trade_date"]:x for x in challenger};bl=_lineage(baseline_ledger);cl=_lineage(challenger_ledger);regimes=regimes or {};rows=[]
    for day in sorted(set(b)|set(c)):
        left=b.get(day);right=c.get(day);same=bool(not (left and right) or (bl.get(left["buy_event_id"])==cl.get(right["buy_event_id"]) and bl.get(left["sell_event_id"])==cl.get(right["sell_event_id"])))
        rows.append({"trade_date":day,"baseline_return":float(left["net_return"]) if left else 0.0,"challenger_return":float(right["net_return"]) if right else 0.0,"baseline_traded":left is not None,"challenger_traded":right is not None,"same_window":same,"lineage_valid":same,"regime":regimes.get(day,"UNKNOWN")})
    return rows
