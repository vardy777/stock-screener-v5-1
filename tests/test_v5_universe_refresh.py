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
def test_native_universe_refresh_rejects_large_shrinkage_or_churn():
 with TemporaryDirectory() as d:
  root=Path(d);UniverseV1.build(trade_date="2026-08-14",created_at=NOW-timedelta(days=3),codes=["000001","000002","600000"],sources=["prior"]).save(root)
  with pytest.raises(ContractViolation,match="anomaly gate"):refresh(root,now=NOW,fetch_json=provider(["000001"]))
