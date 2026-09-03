from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import random

import pytest

from shared_core.core import CHINA_TZ, ContractViolation
from v5_1.master_sources import CrossVerifiedMasterDirectory, SSEOfficialMasterSource, SZSEOfficialMasterSource
from v5_1.runtime import V51Runtime


NOW = datetime(2026, 9, 2, 8, 10, tzinfo=CHINA_TZ)


def _transport(payload, *, status=200):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return lambda _url: (status, raw)


def _a_row(code, *, stock_type="1", listing="20200101", num="1", **changes):
    row = {
        "A_STOCK_CODE": code,
        "B_STOCK_CODE": "-",
        "COMPANY_CODE": code,
        "COMPANY_ABBR": f"公司{code}",
        "FULL_NAME": f"公司{code}股份有限公司",
        "SEC_NAME_FULL": f"公司{code}",
        "LIST_DATE": listing,
        "DELIST_DATE": "-",
        "STATE_CODE": "2",
        "STATE_CODE_STOCK": "4",
        "STOCK_TYPE": stock_type,
        "LIST_BOARD": "1",
        "PRODUCT_STATUS": "D F N",
        "NUM": num,
    }
    row.update(changes)
    return row


def _ab_pair(index):
    a_code = f"{600000 + index:06d}"
    b_code = f"{900000 + index:06d}"
    common = {
        "A_STOCK_CODE": a_code,
        "B_STOCK_CODE": b_code,
        "COMPANY_CODE": a_code,
        "COMPANY_ABBR": f"双股公司{index}",
        "FULL_NAME": f"双股公司{index}股份有限公司",
        "DELIST_DATE": "-",
        "STATE_CODE": "2",
        "STATE_CODE_STOCK": "4",
        "LIST_BOARD": "1",
        "PRODUCT_STATUS": "D F N",
    }
    return [
        {**common, "SEC_NAME_FULL": f"双股公司{index}", "LIST_DATE": "20010102", "STOCK_TYPE": "1", "NUM": f"a-{index}"},
        {**common, "SEC_NAME_FULL": f"双股公司{index}B", "LIST_DATE": "19990102", "STOCK_TYPE": "2", "NUM": f"b-{index}"},
    ]


def _day1_failure_shape_rows():
    # Reproduces the full incident cardinality, not a two-row toy duplicate:
    # 2,516 raw -> 2,506 RC1-valid -> 2,462 unique -> 44 A/B duplicate groups.
    rows = [_a_row(f"{601000 + index:06d}", num=f"single-{index}") for index in range(2418)]
    for index in range(44):
        rows.extend(_ab_pair(index))
    rows.extend(
        {
            "A_STOCK_CODE": "-",
            "COMPANY_CODE": f"{605000 + index:06d}",
            "COMPANY_ABBR": "非A股身份",
            "LIST_DATE": "20200101",
            "STOCK_TYPE": "2",
            "NUM": f"invalid-{index}",
        }
        for index in range(10)
    )
    return rows


def _discover(rows):
    return SSEOfficialMasterSource(_transport({"result": rows})).discover()


def _semantic(rows, diagnostic):
    stable_rows = [{key: value for key, value in row.items() if key != "retrieved_at"} for row in rows]
    stable_diag = {
        key: diagnostic[key]
        for key in (
            "raw_record_count",
            "parsed_record_count",
            "canonical_record_count",
            "unique_symbol_count",
            "duplicate_group_count",
            "classification_counts",
            "excluded_record_count",
            "invalid_record_count",
        )
    }
    payload = json.dumps({"rows": stable_rows, "diagnostic": stable_diag}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def test_day1_failure_shape_canonicalizes_only_after_all_44_groups_are_classified():
    rows, diagnostic = _discover(_day1_failure_shape_rows())
    assert len(rows) == 2462
    assert len({row["code"] for row in rows}) == 2462
    assert diagnostic["raw_record_count"] == 2516
    assert diagnostic["parsed_record_count"] == 2506
    assert diagnostic["duplicate_group_count"] == 44
    assert diagnostic["classification_counts"] == {"CATEGORY_VARIANT": 44}
    assert diagnostic["unexplained_duplicate_groups"] == 0
    assert (
        diagnostic["canonical_record_count"]
        + diagnostic["excluded_record_count"]
        + diagnostic["invalid_record_count"]
        == diagnostic["raw_record_count"]
    )


def test_canonicalization_is_invariant_to_original_reverse_sorted_and_seeded_shuffle():
    original = _day1_failure_shape_rows()
    variants = [
        original,
        list(reversed(original)),
        sorted(original, key=lambda row: (str(row.get("A_STOCK_CODE")), str(row.get("STOCK_TYPE")), str(row.get("NUM")))),
    ]
    shuffled = list(original)
    random.Random(20260902).shuffle(shuffled)
    variants.append(shuffled)
    results = [_discover(rows) for rows in variants]
    assert len({_semantic(rows, diagnostic) for rows, diagnostic in results}) == 1


def test_category_variant_uses_a_share_row_not_input_order_or_b_share_listing_date():
    pair = list(reversed(_ab_pair(3)))
    rows, diagnostic = _discover(pair)
    assert len(rows) == 1
    assert {key: value for key, value in rows[0].items() if key != "retrieved_at"} == {
        "code": "600003",
        "exchange": "SSE",
        "name": "双股公司3",
        "listing_date": "2001-01-02",
        "source_family": "sse",
        "source_url": "https://query.sse.com.cn/sseQuery/commonQuery.do",
        "source_record_id": "sse:a-share:600003",
        "master_status": "ACTIVE",
    }
    assert diagnostic["duplicate_classifications"][0]["classification"] == "CATEGORY_VARIANT"
    assert diagnostic["duplicate_classifications"][0]["excluded_source_record_ids"] == ["sse-row:b-3"]


def test_exact_business_duplicate_collapses_deterministically_and_keeps_lineage():
    first = _a_row("600100", num="2")
    second = _a_row("600100", num="1")
    rows, diagnostic = _discover([first, second])
    assert len(rows) == 1
    item = diagnostic["duplicate_classifications"][0]
    assert item["classification"] == "EXACT_DUPLICATE_SOURCE_ROW"
    assert item["source_record_ids"] == ["sse-row:1", "sse-row:2"]
    assert item["decision"] == "COLLAPSE_EXACT_DUPLICATE"
    assert rows[0]["source_record_id"] == "sse:a-share:600100"


def test_same_symbol_current_identity_conflict_fails_closed_with_structured_cause():
    rows = [_a_row("600200", num="1"), _a_row("600200", num="2", COMPANY_ABBR="冲突公司")]
    with pytest.raises(ContractViolation) as caught:
        _discover(rows)
    assert "AMBIGUOUS_CURRENT_IDENTITY" in str(caught.value)
    diagnostic = caught.value.diagnostic
    assert diagnostic["source"] == "SSE"
    assert diagnostic["error_code"] == "AMBIGUOUS_CURRENT_IDENTITY"
    assert diagnostic["raw_record_count"] == 2
    assert diagnostic["parsed_record_count"] == 2
    assert diagnostic["duplicate_group_count"] == 1
    assert diagnostic["conflicting_symbols_sample"] == ["600200"]


def test_unknown_duplicate_category_shape_fails_closed_instead_of_guessing():
    rows = [_a_row("600201", stock_type="1", num="1"), _a_row("600201", stock_type="8", num="2")]
    with pytest.raises(ContractViolation) as caught:
        _discover(rows)
    assert caught.value.diagnostic["error_code"] == "DUPLICATE_SECURITY_IDENTITY"
    assert caught.value.diagnostic["classification_counts"] == {"UNKNOWN": 1}


def test_delisted_row_does_not_become_current_identity():
    rows, diagnostic = _discover(
        [
            _a_row("600300", DELIST_DATE="20250801", STATE_CODE="3", STATE_CODE_STOCK="6", PRODUCT_STATUS="-"),
            _a_row("600301"),
        ]
    )
    assert [row["code"] for row in rows] == ["600301"]
    assert diagnostic["historical_or_delisted_record_count"] == 1
    assert diagnostic["unique_symbol_count"] == 2
    assert diagnostic["canonical_record_count"] == 1


def test_current_and_explicitly_delisted_identity_coexist_as_one_current_record():
    historical = _a_row(
        "600302",
        num="old",
        COMPANY_ABBR="历史公司",
        FULL_NAME="历史公司股份有限公司",
        LIST_DATE="19990101",
        DELIST_DATE="20100101",
        STATE_CODE="3",
        STATE_CODE_STOCK="6",
        PRODUCT_STATUS="-",
    )
    current = _a_row("600302", num="current", LIST_DATE="20200101")
    rows, diagnostic = _discover([historical, current])
    assert [row["code"] for row in rows] == ["600302"]
    assert rows[0]["name"] == "公司600302"
    fact = diagnostic["duplicate_classifications"][0]
    assert fact["classification"] == "CURRENT_PLUS_DELISTED"
    assert fact["selected_source_record_id"] == "sse-row:current"
    assert fact["excluded_source_record_ids"] == ["sse-row:old"]


def test_delisted_ab_pair_is_classified_but_not_promoted_to_current_master():
    pair = [
        {**row, "DELIST_DATE": "20250801", "STATE_CODE": "3", "STATE_CODE_STOCK": "6", "PRODUCT_STATUS": "-"}
        for row in _ab_pair(9)
    ]
    rows, diagnostic = _discover([*pair, _a_row("600999")])
    assert [row["code"] for row in rows] == ["600999"]
    assert diagnostic["classification_counts"] == {"CATEGORY_VARIANT": 1}
    assert diagnostic["duplicate_classifications"][0]["canonicalized"] is False
    assert diagnostic["duplicate_classifications"][0]["decision"] == "EXCLUDE_DELISTED_CATEGORY_GROUP"


def test_invalid_nonempty_delisting_date_is_ambiguous_and_fails_closed():
    with pytest.raises(ContractViolation) as caught:
        _discover([_a_row("600998", DELIST_DATE="not-a-date")])
    assert caught.value.diagnostic["error_code"] == "SSE_CANONICALIZATION_FAILURE"
    assert caught.value.diagnostic["conflicting_symbols_sample"] == ["600998"]


def test_invalid_a_code_never_falls_back_to_company_code():
    with pytest.raises(ContractViolation) as caught:
        _discover(
            [
                {
                    "A_STOCK_CODE": "-",
                    "COMPANY_CODE": "600999",
                    "COMPANY_ABBR": "公司代码不是A股代码",
                    "LIST_DATE": "20200101",
                    "STOCK_TYPE": "2",
                }
            ]
        )
    assert "OFFICIAL_SOURCE_EMPTY" in str(caught.value)


def test_http_parse_empty_and_canonical_conflict_are_distinct_errors():
    with pytest.raises(RuntimeError, match="HTTP 503") as http_error:
        SSEOfficialMasterSource(_transport({}, status=503)).discover()
    assert http_error.value.diagnostic["error_code"] == "OFFICIAL_SOURCE_HTTP_FAILURE"
    with pytest.raises(ContractViolation, match="OFFICIAL_SOURCE_PARSE_FAILURE") as parse_error:
        SSEOfficialMasterSource(lambda _url: (200, "not-json")).discover()
    assert parse_error.value.diagnostic["underlying_exception_type"] == "ContractViolation"
    with pytest.raises(ContractViolation) as malformed_error:
        SSEOfficialMasterSource(lambda _url: (200, "{not-json}" )).discover()
    assert malformed_error.value.diagnostic["underlying_exception_type"] == "JSONDecodeError"
    with pytest.raises(ContractViolation, match="OFFICIAL_SOURCE_EMPTY"):
        _discover([])
    with pytest.raises(ContractViolation, match="AMBIGUOUS_CURRENT_IDENTITY"):
        _discover([_a_row("600400"), _a_row("600400", COMPANY_ABBR="不同身份")])


def test_transport_failure_has_source_specific_unavailable_diagnostic():
    def failed_transport(_url):
        raise OSError("network unavailable")

    source = SSEOfficialMasterSource(failed_transport)
    with pytest.raises(RuntimeError, match="OFFICIAL_SOURCE_UNAVAILABLE") as caught:
        source.discover()
    assert caught.value.diagnostic == {
        "source": "SSE",
        "stage": "OFFICIAL_SOURCE_REQUEST",
        "endpoint": "https://query.sse.com.cn/sseQuery/commonQuery.do",
        "error_code": "OFFICIAL_SOURCE_UNAVAILABLE",
        "underlying_exception_type": "OSError",
        "underlying_exception_message": "network unavailable",
    }


class _Directory:
    provider_family = "eastmoney"
    source_id = "eastmoney_market_directory"

    def discover(self):
        return (), {"provider_family": "eastmoney", "official_independent_source": False}


def test_canonical_sse_and_unchanged_szse_form_unique_authoritative_merge():
    sse = SSEOfficialMasterSource(_transport({"result": _ab_pair(5)}))
    szse = SZSEOfficialMasterSource(
        _transport([{"data": [{"agdm": "000001", "agjc": "平安银行", "agssrq": "1991-04-03"}]}])
    )
    rows, diagnostic = CrossVerifiedMasterDirectory(eastmoney=_Directory(), sse=sse, szse=szse).discover()
    assert [row["code"] for row in rows] == ["000001", "600005"]
    assert diagnostic["sse"]["canonical_record_count"] == 1
    assert diagnostic["szse"]["valid_records"] == 1


def test_sse_transport_outage_never_falls_back_to_eastmoney_only():
    class _Outage:
        def discover(self):
            raise RuntimeError("SSE OFFICIAL_SOURCE_UNAVAILABLE")

    source = CrossVerifiedMasterDirectory(
        eastmoney=_Directory(),
        sse=_Outage(),
        szse=SZSEOfficialMasterSource(
            _transport([{"data": [{"agdm": "000001", "agjc": "平安银行", "agssrq": "1991-04-03"}]}])
        ),
    )
    with pytest.raises(RuntimeError, match="OFFICIAL_SOURCE_UNAVAILABLE"):
        source.discover()


def test_runtime_failure_fact_preserves_sanitized_canonicalization_diagnostic(tmp_path):
    class _Calendar:
        def is_open(self, _day):
            return True

        def next_open(self, day):
            return day

    source = SSEOfficialMasterSource(
        _transport({"result": [_a_row("600500"), _a_row("600500", COMPANY_ABBR="冲突公司")]})
    )
    runtime = V51Runtime(
        tmp_path,
        mode="TEST",
        clock=lambda: NOW,
        master_provider=source,
        calendar=_Calendar(),
    )
    result = runtime.run("preflight")
    assert result["passed"] is False
    assert result["failure"]["diagnostic"]["error_code"] == "AMBIGUOUS_CURRENT_IDENTITY"
    assert result["failure"]["diagnostic"]["raw_record_count"] == 2
    assert "raw_content_b64" not in result["failure"]["diagnostic"]


def test_frozen_release_scope_contains_the_rc2_canonicalization_contract():
    contract = Path(__file__).resolve().parents[1] / "docs" / "V5_1_SSE_SECURITY_MASTER_CANONICALIZATION_CONTRACT.md"
    assert contract.is_file()
    assert "CANONICALIZATION CONTRACT = FROZEN" in contract.read_text(encoding="utf-8")
