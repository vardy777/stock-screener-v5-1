import pytest
from shared_core.core import ContractViolation
from v5_1.master_sources import SSE_OFFICIAL,SZSE_OFFICIAL,EASTMONEY_DIRECTORY,build_independent_master
from v5_1.scheduler_plan import build

NOW="2026-08-27T18:00:00+08:00"
def sse(name="浦发银行"):return [{"symbol":"600000","exchange":"SSE","board":"MAIN","security_name":name,"listing_date":"1999-11-10"}]
def test_official_fixture_parsers_and_independence():
 rows=build_independent_master(((SSE_OFFICIAL,sse()),(SZSE_OFFICIAL,[{"symbol":"000001","exchange":"SZSE","board":"MAIN","security_name":"平安银行","listing_date":"1991-04-03"}])),NOW)
 assert {x.symbol for x in rows}=={"600000","000001"} and SSE_OFFICIAL.live_status=="PENDING_LIVE_ACCEPTANCE"
def test_eastmoney_only_is_not_independent_fallback():
 with pytest.raises(ContractViolation,match="independent"):build_independent_master(((EASTMONEY_DIRECTORY,sse()),),NOW)
def test_official_parser_rejects_exchange_conflict():
 with pytest.raises(ContractViolation,match="exchange"):SSE_OFFICIAL.parse([{"symbol":"600000","exchange":"SZSE","board":"MAIN","security_name":"冲突","listing_date":"1999-11-10"}],NOW)
def test_official_parser_rejects_string_boolean():
 with pytest.raises(ContractViolation,match="strict boolean"):SSE_OFFICIAL.parse([{"symbol":"600000","exchange":"SSE","board":"MAIN","security_name":"浦发银行","listing_date":"1999-11-10","is_a_share":"true"}],NOW)
def test_scheduler_plan_is_report_only_and_moves_morning_to_0935():
 plan=build();assert plan["report_only"] and not plan["authorized"] and not plan["registers_tasks"] and not plan["duplicate_business_writers_allowed"]
 assert plan["all_definitions_disabled"] and all(not row["enabled"] for row in plan["changes"])
 recovery=next(x for x in plan["changes"] if x["task"]=="V51-Shadow-Master-Recovery");assert recovery["new"].startswith("08:10/08:30/08:50/09:05/09:20")
 change=next(x for x in plan["changes"] if x["task"]=="Morning-Facts-Daily");assert change["old"]=="09:25:05" and change["new"]=="09:35:00"
