from datetime import datetime
import base64
import json

import pytest

from shared_core.core import CHINA_TZ, ContractViolation
from shared_core.calendar import TradingCalendar
from v5_1.master_evidence import DirectoryResponseFactV51, MasterEvidenceRepository, MasterMatchFactV51
from v5_1.master_sources import CrossVerifiedMasterDirectory, SSEOfficialMasterSource, SZSEOfficialMasterSource
from v5_1.runtime import V51Runtime

NOW=datetime(2026,8,31,8,30,tzinfo=CHINA_TZ)
RAW_A=base64.b64encode(b"a").decode();RAW_B=base64.b64encode(b"b").decode()

def transport(payload):return lambda _url:(200,json.dumps(payload,ensure_ascii=False))
def sse():return SSEOfficialMasterSource(transport({"result":[{"A_STOCK_CODE":"600000","COMPANY_ABBR":"浦发银行","LISTING_DATE":"1999-11-10"}]}))
def szse():return SZSEOfficialMasterSource(transport([{"data":[{"agdm":"000001","agjc":"平安银行","agssrq":"1991-04-03"}]}]))

class Outage:
    def discover(self):raise RuntimeError("eastmoney unavailable")
class OpenCalendar:
    def is_open(self,_day):return True
    def next_open(self,day):return day
class NoMarket:pass

def test_official_base_survives_eastmoney_outage_and_records_degradation():
    rows,diag=CrossVerifiedMasterDirectory(eastmoney=Outage(),sse=sse(),szse=szse()).discover()
    assert {x["code"] for x in rows}=={"600000","000001"}
    assert diag["verification_status"]=="DEGRADED_THIRD_PARTY_UNAVAILABLE"
    assert all(x["outcome"]=="THIRD_PARTY_UNAVAILABLE" for x in diag["matches"])

def test_shadow_preflight_persists_resolvable_evidence_chain(tmp_path):
    runtime=V51Runtime(tmp_path,mode="SHADOW",clock=lambda:NOW,provider=NoMarket(),master_provider=CrossVerifiedMasterDirectory(eastmoney=Outage(),sse=sse(),szse=szse()),calendar=OpenCalendar())
    result=runtime.run("preflight")
    assert result["passed"],result
    verification=runtime.master.require_fresh(NOW.date(),NOW,TradingCalendar())
    assert len(verification.response_ids)==2 and len(verification.match_ids)==2
    assert runtime.master_evidence.resolve(verification.response_ids,verification.match_ids,runtime.master.versions())

def test_tampered_response_missing_entity_forged_match_and_duplicate_symbol_fail(tmp_path):
    repo=MasterEvidenceRepository(tmp_path)
    import hashlib
    official=DirectoryResponseFactV51.build(provider_family="sse",exchange="SSE",endpoint="https://sse",retrieved_at=NOW,raw_sha256=hashlib.sha256(b"a").hexdigest(),raw_content_b64=RAW_A,record_count=1);repo.save_response(official)
    third=DirectoryResponseFactV51.build(provider_family="eastmoney",exchange="ALL",endpoint="https://eastmoney",retrieved_at=NOW,raw_sha256=hashlib.sha256(b"b").hexdigest(),raw_content_b64=RAW_B,record_count=1);repo.save_response(third)
    with pytest.raises(ContractViolation,match="missing response"):
        repo.save_match(MasterMatchFactV51.build(symbol="600000",exchange="SSE",official_response_id="v51dirresponse1-"+"0"*64,third_party_response_id=third.response_id,official_name="浦发银行",official_listing_date="1999-11-10",third_party_name="浦发银行",third_party_listing_date="1999-11-10",outcome="MATCH",matched_at=NOW))
    path=repo.save_response(official);row=json.loads(path.read_text(encoding="utf-8"));row["raw_content_b64"]=RAW_B;path.write_text(json.dumps(row),encoding="utf-8")
    with pytest.raises(ContractViolation,match="raw content/hash"):
        repo.responses()

def test_same_family_alias_cannot_be_independent_match(tmp_path):
    repo=MasterEvidenceRepository(tmp_path)
    import hashlib
    a=DirectoryResponseFactV51.build(provider_family="sse",exchange="SSE",endpoint="https://a",retrieved_at=NOW,raw_sha256=hashlib.sha256(b"a").hexdigest(),raw_content_b64=RAW_A,record_count=1)
    b=DirectoryResponseFactV51.build(provider_family="sse",exchange="ALL",endpoint="https://alias",retrieved_at=NOW,raw_sha256=hashlib.sha256(b"b").hexdigest(),raw_content_b64=RAW_B,record_count=1)
    repo.save_response(a);repo.save_response(b)
    match=MasterMatchFactV51.build(symbol="600000",exchange="SSE",official_response_id=a.response_id,third_party_response_id=b.response_id,official_name="浦发银行",official_listing_date="1999-11-10",third_party_name="浦发银行",third_party_listing_date="1999-11-10",outcome="MATCH",matched_at=NOW);repo.save_match(match)
    class Version:symbol="600000"
    with pytest.raises(ContractViolation,match="same-family"):
        repo.resolve([a.response_id,b.response_id],[match.match_id],[Version()])
