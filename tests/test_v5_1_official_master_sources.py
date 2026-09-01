from datetime import datetime
import json

import pytest

from shared_core.core import CHINA_TZ, ContractViolation
from shared_core.calendar import TradingCalendar
from v5_1.master_sources import (
    CrossVerifiedMasterDirectory,
    SSEOfficialMasterSource,
    SZSEOfficialMasterSource,
    normalize_security_name,
)
from v5_1.runtime import V51Runtime


NOW = datetime(2026, 8, 28, 8, 30, tzinfo=CHINA_TZ)


def transport(payload, status=200):
    return lambda _url: (status, json.dumps(payload, ensure_ascii=False))


def sse(rows=None):
    rows = rows or [{"A_STOCK_CODE": "600000", "COMPANY_ABBR": "浦发银行", "LISTING_DATE": "1999-11-10"}]
    return SSEOfficialMasterSource(transport({"result": rows}))


def szse(rows=None):
    rows = rows or [{"agdm": "000001", "agjc": "平安银行", "agssrq": "1991-04-03"}]
    return SZSEOfficialMasterSource(transport([{"data": rows}]))


class Directory:
    provider_family = "eastmoney"
    source_id = "eastmoney_market_directory"

    def __init__(self, rows):
        self.rows = rows

    def discover(self):
        return tuple(self.rows), {"provider_family": "eastmoney", "official_independent_source": False}


def directory(*rows):
    return Directory(rows)


def test_sse_and_szse_official_parse_real_contract_fields():
    sse_rows, sse_diag = sse().discover()
    szse_rows, szse_diag = szse().discover()
    assert sse_rows[0]["exchange"] == "SSE" and sse_rows[0]["source_family"] == "sse"
    assert szse_rows[0]["exchange"] == "SZSE" and szse_rows[0]["source_family"] == "szse"
    assert sse_diag["valid_records"] == szse_diag["valid_records"] == 1
    assert sse_rows[0]["source_url"].startswith("https://query.sse.com.cn/")
    assert szse_rows[0]["source_url"].startswith("https://www.szse.cn/")


def test_official_exchange_cannot_verify_other_exchange_symbol():
    with pytest.raises(ContractViolation, match="no valid identity"):
        sse([{"A_STOCK_CODE": "000001", "COMPANY_ABBR": "平安银行", "LISTING_DATE": "1991-04-03"}]).discover()
    with pytest.raises(ContractViolation, match="no valid identity"):
        szse([{"agdm": "600000", "agjc": "浦发银行", "agssrq": "1999-11-10"}]).discover()


def test_eastmoney_plus_relevant_official_exchange_verifies_both_markets():
    source = CrossVerifiedMasterDirectory(
        eastmoney=directory(
            {"code": "600000", "name": " 浦发银行 ", "listing_date": "1999-11-10"},
            {"code": "000001", "name": "平安银行", "listing_date": "1991-04-03"},
        ),
        sse=sse(),
        szse=szse(),
    )
    rows, diag = source.discover()
    assert {row["code"] for row in rows} == {"600000", "000001"}
    assert diag["official_independent_source"] is True
    assert diag["sse"]["verified"] == diag["szse"]["verified"] == 1
    assert diag["independent_source_families"] == ["sse", "szse"]


def test_official_base_always_reads_both_exchange_directories():
    sse_only = CrossVerifiedMasterDirectory(
        eastmoney=directory({"code": "600000", "name": "浦发银行", "listing_date": "1999-11-10"}),
        sse=sse(),
        szse=szse(),
    )
    rows, diag = sse_only.discover()
    assert {row["code"] for row in rows} == {"600000", "000001"}
    assert diag["independent_source_families"] == ["sse", "szse"]
    assert diag["verification_status"] == "DEGRADED_THIRD_PARTY_PARTIAL"


@pytest.mark.parametrize(
    "official_sse,official_szse,match",
    [
        (sse([{"A_STOCK_CODE": "600000", "COMPANY_ABBR": "另一公司", "LISTING_DATE": "1999-11-10"}]), szse(), "conflicts=1"),
        (sse([{"A_STOCK_CODE": "600000", "COMPANY_ABBR": "浦发银行", "LISTING_DATE": "2000-01-01"}]), szse(), "conflicts=1"),
        (sse([{"A_STOCK_CODE": "600000", "COMPANY_ABBR": "浦发银行", "LISTING_DATE": ""}]), szse(), "no valid identity"),
    ],
)
def test_identity_conflict_or_missing_listing_date_fails_closed(official_sse, official_szse, match):
    source = CrossVerifiedMasterDirectory(
        eastmoney=directory({"code": "600000", "name": "浦发银行", "listing_date": "1999-11-10"}),
        sse=official_sse,
        szse=official_szse,
    )
    with pytest.raises(ContractViolation, match=match):
        source.discover()


@pytest.mark.parametrize("failed", ["sse", "szse"])
def test_official_source_outage_never_falls_back_to_eastmoney_only(failed):
    class Outage:
        def discover(self):
            raise RuntimeError("official source unavailable")

    source = CrossVerifiedMasterDirectory(
        eastmoney=directory(
            {"code": "600000", "name": "浦发银行", "listing_date": "1999-11-10"},
            {"code": "000001", "name": "平安银行", "listing_date": "1991-04-03"},
        ),
        sse=Outage() if failed == "sse" else sse(),
        szse=Outage() if failed == "szse" else szse(),
    )
    with pytest.raises(RuntimeError, match="official source unavailable"):
        source.discover()


def test_name_normalization_is_strict_but_ignores_format_and_risk_prefix():
    assert normalize_security_name("＊ＳＴ　浦发银行") == normalize_security_name("浦发银行")
    assert normalize_security_name("浦发银行") != normalize_security_name("浦发银")


def test_bse_is_explicitly_excluded_not_verified_by_szse():
    source = CrossVerifiedMasterDirectory(
        eastmoney=directory(
            {"code": "600000", "name": "浦发银行", "listing_date": "1999-11-10"},
            {"code": "830000", "name": "北交样本", "listing_date": "2020-01-01"},
        ),
        sse=sse(),
        szse=szse(),
    )
    rows, diag = source.discover()
    assert {row["code"] for row in rows} == {"600000", "000001"}
    assert diag["bse"] == {"status": "EXCLUDED_BY_CONTRACT", "symbols": ["830000"]}


class OpenCalendar:
    def is_open(self, _day):
        return True

    def next_open(self, day):
        return day


class NoMarketProvider:
    pass


def test_shadow_preflight_persists_relevant_official_lineage(tmp_path):
    source = CrossVerifiedMasterDirectory(
        eastmoney=directory(
            {"code": "600000", "name": "浦发银行", "listing_date": "1999-11-10"},
            {"code": "000001", "name": "平安银行", "listing_date": "1991-04-03"},
        ),
        sse=sse(),
        szse=szse(),
    )
    runtime = V51Runtime(
        tmp_path,
        mode="SHADOW",
        clock=lambda: NOW,
        provider=NoMarketProvider(),
        master_provider=source,
        calendar=OpenCalendar(),
    )
    result = runtime.run("preflight")
    assert result["passed"], result
    versions = runtime.master.versions()
    assert {row.source_family for row in versions} == {"sse", "szse"}
    verification = runtime.master.require_fresh("2026-08-28", NOW, TradingCalendar())
    assert verification.source_families == ("eastmoney", "sse", "szse")
    assert verification.independent_source_families == ("sse", "szse")


def test_eastmoney_only_or_same_family_alias_cannot_verify_shadow(tmp_path):
    class EastmoneyOnly(Directory):
        source_id = "eastmoney_alternate_host"

        def discover(self):
            rows, diagnostics = super().discover()
            return rows, {
                **diagnostics,
                "source_families": ["eastmoney"],
                "independent_source_families": ["eastmoney"],
                "official_independent_source": True,
            }

    runtime = V51Runtime(
        tmp_path,
        mode="SHADOW",
        clock=lambda: NOW,
        provider=NoMarketProvider(),
        master_provider=EastmoneyOnly([{"code": "600000", "name": "浦发银行", "listing_date": "1999-11-10"}]),
        calendar=OpenCalendar(),
    )
    result = runtime.run("preflight")
    assert result["passed"] is False
    assert "Eastmoney-only" in result["error"]
