from datetime import datetime
import json
import pytest
from shared_core.core import CHINA_TZ,ContractViolation
from shared_core.calendar import TradingCalendar
from v5_1.security_master import MasterVerificationV1,SecurityMasterRepository,SecurityMasterVersionV1,reconcile_provider_records
from v5_1.tradability import DailySecurityStatusRepository,DailySecurityStatusV1,derive_tradability

DAY="2026-08-28";NOW=datetime(2026,8,28,8,30,tzinfo=CHINA_TZ);CALENDAR=TradingCalendar()
def master(symbol="600000",**kw):
 return SecurityMasterVersionV1.build(symbol=symbol,exchange="SSE" if symbol.startswith("6") else "SZSE",board="MAIN",security_name=kw.pop("security_name","浦发银行"),listing_date="1999-11-10",valid_from=kw.pop("valid_from","1999-11-10"),known_at=kw.pop("known_at",NOW),source_family=kw.pop("source_family","sse_official"),source_record_id=kw.pop("source_record_id",symbol),**kw)
def status(symbol="600000",**kw):
    families=kw.pop("source_families",["sina","tencent"])
    snapshots=kw.pop("source_snapshot_ids",[f"ms1-{name}-{symbol}" for name in families])
    return DailySecurityStatusV1.build(trade_date=DAY,symbol=symbol,observed_at=kw.pop("observed_at",NOW),known_at=kw.pop("known_at",NOW),source_families=families,source_snapshot_ids=snapshots,**kw)
def verified(repo,rows,*,verified_day=DAY,verified_at=NOW):
 for row in rows:repo.append(row)
 fact=MasterVerificationV1.build(verified_for_trade_date=verified_day,verified_at=verified_at,source_families=sorted({x.source_family for x in rows}),independent_source_families=sorted({x.source_family for x in rows}),master_version_ids=[x.version_id for x in rows],record_count=len(rows));repo.verify(fact);return fact
def derive(tmp_path,rows,statuses,*,decided_at=NOW,verification_day=DAY,verification_at=NOW,store_statuses=True):
 repo=SecurityMasterRepository(tmp_path/"master");verification=verified(repo,rows,verified_day=verification_day,verified_at=verification_at);status_repo=DailySecurityStatusRepository(tmp_path/"status")
 if store_statuses:
  for item in statuses:status_repo.save(item)
 return derive_tradability(rows,statuses,trade_date=DAY,decided_at=decided_at,master_verification=verification,master_repository=repo,status_repository=status_repo,calendar=CALENDAR)

def test_master_first_build_increment_change_delist_and_pit_are_immutable(tmp_path):
 repo=SecurityMasterRepository(tmp_path);first=master();repo.append(first);renamed=master(security_name="浦发银行新名",valid_from="2026-09-01",known_at="2026-08-31T18:00:00+08:00",source_record_id="rename");delisted=master(master_status="DELISTED",delisting_date="2026-10-01",valid_from="2026-10-01",known_at="2026-09-30T18:00:00+08:00",source_record_id="delist");repo.append(renamed);repo.append(delisted)
 assert repo.as_of(DAY,NOW)[0].version_id==first.version_id and repo.as_of("2026-09-02","2026-09-02T08:00:00+08:00")[0].security_name=="浦发银行新名" and repo.as_of("2026-10-02","2026-10-02T08:00:00+08:00")==()

def test_verification_pit_future_same_day_previous_stale_and_missing(tmp_path):
 row=master();repo=SecurityMasterRepository(tmp_path);verified(repo,[row],verified_at="2026-08-28T09:36:00+08:00")
 with pytest.raises(ContractViolation,match="stale"):repo.require_fresh(DAY,"2026-08-28T09:35:00+08:00",CALENDAR)
 previous_row=master(known_at="2026-08-27T17:00:00+08:00",source_record_id="previous");previous_repo=SecurityMasterRepository(tmp_path/"previous");previous=verified(previous_repo,[previous_row],verified_day="2026-08-27",verified_at="2026-08-27T18:00:00+08:00")
 assert previous_repo.require_fresh(DAY,NOW,CALENDAR).verification_id==previous.verification_id
 with pytest.raises(ContractViolation,match="TradingCalendar"):previous_repo.require_fresh(DAY,NOW,["2026-08-27",DAY])
 with pytest.raises(ContractViolation,match="stale"):SecurityMasterRepository(tmp_path/"empty").require_fresh(DAY,NOW,CALENDAR)

def test_verification_missing_or_future_master_version_fails(tmp_path):
 repo=SecurityMasterRepository(tmp_path);row=master();repo.append(row)
 missing=MasterVerificationV1.build(verified_for_trade_date=DAY,verified_at=NOW,source_families=["sse_official"],independent_source_families=["sse_official"],master_version_ids=["smv1-missing"],record_count=1)
 with pytest.raises(ContractViolation,match="missing master"):repo.verify(missing)
 future=master(known_at="2026-08-28T09:00:00+08:00",source_record_id="future");repo.append(future);fact=MasterVerificationV1.build(verified_for_trade_date=DAY,verified_at=NOW,source_families=["sse_official"],independent_source_families=["sse_official"],master_version_ids=[future.version_id],record_count=1)
 with pytest.raises(ContractViolation,match="future master"):repo.verify(fact)

def test_master_tamper_and_independent_conflict_fail(tmp_path):
 repo=SecurityMasterRepository(tmp_path);path=repo.append(master());payload=json.loads(path.read_text(encoding="utf-8"));payload["security_name"]="篡改";path.write_text(json.dumps(payload),encoding="utf-8")
 with pytest.raises(ContractViolation,match="content-address"):repo.versions()
 official=master();conflict=master(security_name="冲突",source_family="szse_official",source_record_id="other")
 with pytest.raises(ContractViolation,match="conflict"):reconcile_provider_records({"sse_official":[official],"szse_official":[conflict]},["sse_official","szse_official"])

@pytest.mark.parametrize("value",["true",1])
def test_master_strict_boolean(value):
 with pytest.raises(ContractViolation,match="strict boolean"):master(is_a_share=value)

@pytest.mark.parametrize("field,value",[("is_st","false"),("suspended",0),("status_known","true"),("conflict",1)])
def test_daily_status_strict_boolean(field,value):
 with pytest.raises(ContractViolation,match="strict boolean"):status(**{field:value})

@pytest.mark.parametrize("flags,reason",[({"is_st":True},"ST"),({"suspended":True},"SUSPENDED"),({"delisting_period":True},"DELISTING_PERIOD"),({"new_listing":True},"NEW_LISTING")])
def test_daily_status_stored_and_special_states_are_excluded(tmp_path,flags,reason):
 fact=derive(tmp_path,[master()],[status(**flags)]);assert fact.accepted and fact.eligible_symbols==() and fact.rejections[0]["reason"]==reason and fact.status_ids

def test_status_missing_reference_ambiguous_conflict_and_future_fail_closed(tmp_path):
 with pytest.raises(ContractViolation,match="missing or ambiguous"):derive(tmp_path,[master()],[status()],store_statuses=False)
 conflict=derive(tmp_path/"conflict",[master()],[status(conflict=True)]);assert not conflict.accepted and conflict.eligible_symbols==()
 duplicate_a=status();duplicate_b=status(observed_at="2026-08-28T08:29:59+08:00",known_at="2026-08-28T08:29:59+08:00")
 with pytest.raises(ContractViolation,match="duplicate"):derive(tmp_path/"duplicate",[master()],[duplicate_a,duplicate_b])
 with pytest.raises(ContractViolation,match="future"):derive(tmp_path/"future",[master()],[status(known_at="2026-08-28T08:31:00+08:00")])

def test_tradability_rejects_future_master_known_at(tmp_path):
 old=master(known_at="2026-08-27T17:00:00+08:00",source_record_id="old");repo=SecurityMasterRepository(tmp_path/"master");verification=verified(repo,[old],verified_day="2026-08-27",verified_at="2026-08-27T18:00:00+08:00");status_repo=DailySecurityStatusRepository(tmp_path/"status");item=status();status_repo.save(item);future=master(known_at="2026-08-28T08:31:00+08:00",source_record_id="future")
 with pytest.raises(ContractViolation,match="future master"):derive_tradability([future],[item],trade_date=DAY,decided_at=NOW,master_verification=verification,master_repository=repo,status_repository=status_repo,calendar=CALENDAR)

def test_valid_historical_master_and_json_booleans_pass(tmp_path):
 fact=derive(tmp_path,[master(is_a_share=True)],[status(is_st=False,suspended=False)]);assert fact.accepted and fact.eligible_symbols==("600000",)

def test_repository_level_ambiguous_status_cannot_be_bypassed_by_single_supplied_row(tmp_path):
 repo=SecurityMasterRepository(tmp_path/"master");row=master();verification=verified(repo,[row]);status_repo=DailySecurityStatusRepository(tmp_path/"status");first=status();second=status(observed_at="2026-08-28T08:29:59+08:00",known_at="2026-08-28T08:29:59+08:00");status_repo.save(first);status_repo.save(second)
 with pytest.raises(ContractViolation,match="ambiguous as-of"):derive_tradability([row],[first],trade_date=DAY,decided_at=NOW,master_verification=verification,master_repository=repo,status_repository=status_repo,calendar=CALENDAR)
