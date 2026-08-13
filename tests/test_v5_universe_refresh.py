import json
from datetime import datetime,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from v5.core import CHINA_TZ,ContractViolation
from v5.universe import UniverseV1
from v5.universe_refresh import refresh
NOW=datetime(2026,8,17,9,23,tzinfo=CHINA_TZ)
def provider(codes):return lambda *_:{"rc":0,"data":{"diff":[{"f12":x} for x in codes],"total":len(codes)}}
def test_native_universe_refresh_is_content_addressed_and_prior_gated():
 with TemporaryDirectory() as d:
  root=Path(d);prior=UniverseV1.build(trade_date="2026-08-14",created_at=NOW-timedelta(days=3),codes=["000001","000002","600000"],sources=["prior"]);prior.save(root)
  result=refresh(root,now=NOW,fetch_json=provider(["000001","000002","600000"]));assert result["count"]==3 and all(result["checks"].values());assert Path(result["path"]).exists()
def test_first_native_refresh_may_expand_legacy_seed_but_may_not_drop_seed_codes():
 with TemporaryDirectory() as d:
  root=Path(d);UniverseV1.build(trade_date="2026-08-14",created_at=NOW-timedelta(days=3),codes=["000001","000002"],sources=["legacy_daily_archive_seed_migration"]).save(root)
  result=refresh(root,now=NOW,fetch_json=provider(["000001","000002","600000"]));assert result["diagnostics"]["migration_mode"]=="legacy_seed_to_native_directory" and result["checks"]["migration_is_expansion_only"]
 with TemporaryDirectory() as d:
  root=Path(d);UniverseV1.build(trade_date="2026-08-14",created_at=NOW-timedelta(days=3),codes=["000001","000002"],sources=["legacy_daily_archive_seed_migration"]).save(root)
  with pytest.raises(ContractViolation,match="anomaly gate"):refresh(root,now=NOW,fetch_json=provider(["000001","600000"]))
def test_refresh_uses_same_day_seed_as_migration_baseline():
 with TemporaryDirectory() as d:
  root=Path(d);UniverseV1.build(trade_date="2026-08-17",created_at=NOW-timedelta(minutes=1),codes=["000001","000002"],sources=["legacy_daily_archive_seed_migration"]).save(root)
  result=refresh(root,now=NOW,fetch_json=provider(["000001","000002","600000"]));assert result["diagnostics"]["migration_mode"]=="legacy_seed_to_native_directory"
def test_native_universe_refresh_rejects_large_shrinkage_or_churn():
 with TemporaryDirectory() as d:
  root=Path(d);UniverseV1.build(trade_date="2026-08-14",created_at=NOW-timedelta(days=3),codes=["000001","000002","600000"],sources=["prior"]).save(root)
  with pytest.raises(ContractViolation,match="anomaly gate"):refresh(root,now=NOW,fetch_json=provider(["000001"]))
def test_native_universe_refresh_fails_closed_on_budget_or_incomplete_pagination():
 ticks=iter((0,2))
 with pytest.raises(TimeoutError,match="overall budget"):refresh(Path("unused"),now=NOW,fetch_json=provider(["000001"]),overall_budget_seconds=1,monotonic=lambda:next(ticks))
 partial=lambda *_:{"rc":0,"data":{"diff":[],"total":10}}
 with pytest.raises(ContractViolation,match="pagination incomplete"):refresh(Path("unused"),now=NOW,fetch_json=partial)
def test_native_universe_refresh_retries_transient_disconnect_within_budget():
 calls=[]
 def flaky(*_):
  calls.append(1)
  if len(calls)<3:raise ConnectionError("reset")
  return {"rc":0,"data":{"diff":[{"f12":"000001"}],"total":1}}
 from v5.universe_refresh import fetch_codes
 assert fetch_codes(fetch_json=flaky,sleeper=lambda *_:None)==["000001"] and len(calls)==3
def test_native_universe_refresh_follows_provider_actual_page_length_not_requested_size():
 from urllib.parse import parse_qs,urlparse
 def paged(url,_timeout):
  page=int(parse_qs(urlparse(url).query)["pn"][0]);all_codes=[f"00000{x}" for x in range(1,7)];chunk=all_codes[(page-1)*2:page*2];return {"rc":0,"data":{"diff":[{"f12":x} for x in chunk],"total":6}}
 from v5.universe_refresh import fetch_codes
 assert len(fetch_codes(fetch_json=paged,page_size=500))==6
