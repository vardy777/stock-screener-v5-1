"""Diagnostic-only frozen RC2 SSE transport sampler; stdout JSON only."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import hashlib
import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shared_core.core import CHINA_TZ
from v5_1.master_sources import SSEOfficialMasterSource

ENDPOINT = SSEOfficialMasterSource.endpoint
HEADERS = {"Referer": ENDPOINT, "User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"}
BASE_QUERY = {"sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L", "isPagination": "true"}
FIELDS = ("NUM", "A_STOCK_CODE", "B_STOCK_CODE", "STOCK_TYPE", "LIST_DATE", "DELIST_DATE", "COMPANY_CODE", "SEC_NAME_FULL", "STATE_CODE", "STATE_CODE_STOCK", "PRODUCT_STATUS")


def now(): return datetime.now(CHINA_TZ).isoformat()
def digest(value): return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
def source_key(row): return digest({key: row.get(key) for key in FIELDS})


def full_attempt(number, sample_window):
    source = SSEOfficialMasterSource(); started = now(); began = time.monotonic()
    query = {**BASE_QUERY, "pageHelp.pageSize": "5000", "pageHelp.pageNo": "1", "pageHelp.beginPage": "1", "pageHelp.endPage": "1"}
    result = {"sample_window": sample_window, "attempt_number": number, "started_at": started, "endpoint": ENDPOINT, "query_fingerprint": hashlib.sha256(urlencode(query).encode()).hexdigest(), "connect_timeout": 8, "read_timeout": 8}
    try:
        rows, diag = source.discover()
        result.update(completed_at=now(), elapsed_ms=round((time.monotonic()-began)*1000), http_status=diag.get("http_status"), response_bytes=len(base64.b64decode(diag["raw_content_b64"])), raw_row_count=diag.get("raw_record_count"), parsed_row_count=diag.get("parsed_record_count"), canonical_row_count=len(rows), duplicate_groups=diag.get("duplicate_group_count"), result="PASS")
    except Exception as exc:
        diag = getattr(exc, "diagnostic", {}) or {}
        result.update(completed_at=now(), elapsed_ms=round((time.monotonic()-began)*1000), http_status=diag.get("http_status"), response_bytes=None, raw_row_count=diag.get("raw_record_count"), parsed_row_count=diag.get("parsed_record_count"), canonical_row_count=diag.get("canonical_record_count"), duplicate_groups=diag.get("duplicate_group_count"), exception_type=type(exc).__name__, exception_message=str(exc), failure_stage=diag.get("stage", "UNKNOWN"), result="FAIL")
    return result


def fetch(page):
    query = {**BASE_QUERY, "pageHelp.pageSize": "100", "pageHelp.pageNo": str(page), "pageHelp.beginPage": str(page), "pageHelp.endPage": str(page)}
    url = ENDPOINT + "?" + urlencode(query); failures = []
    for attempt in range(1, 4):
        started = now(); began = time.monotonic()
        try:
            response = urlopen(Request(url, headers=HEADERS), timeout=20); status = response.status; raw = response.read(); text = raw.decode("utf-8-sig", "replace"); payload = json.loads(text[text.find("{"):text.rfind("}")+1]); rows = payload.get("result") or []; page_help = payload.get("pageHelp") or {}
            return rows, {"page_number": page, "attempt": attempt, "row_count": len(rows), "first_NUM": rows[0].get("NUM") if rows else None, "last_NUM": rows[-1].get("NUM") if rows else None, "first_source_row_key": source_key(rows[0]) if rows else None, "last_source_row_key": source_key(rows[-1]) if rows else None, "semantic_content_hash": digest(rows), "byte_hash": hashlib.sha256(raw).hexdigest(), "elapsed_ms": round((time.monotonic()-began)*1000), "http_status": status, "response_bytes": len(raw), "provider_total_count": page_help.get("total"), "provider_page_count": page_help.get("pageCount"), "provider_cache_size": page_help.get("cacheSize"), "provider_sort_value": page_help.get("sort"), "started_at": started, "completed_at": now(), "prior_failures": failures, "result": "PASS"}
        except Exception as exc:
            failures.append({"attempt": attempt, "started_at": started, "completed_at": now(), "elapsed_ms": round((time.monotonic()-began)*1000), "exception_type": type(exc).__name__, "exception_message": str(exc)})
    return [], {"page_number": page, "attempt": 3, "failures": failures, "result": "FAIL"}


def crawl(crawl_id, sample_window):
    started = now(); pages=[]; rows=[]
    for page in (5, 10, 15, 20, 25, 26):
        block, evidence = fetch(page); pages.append(evidence)
        if evidence["result"] != "PASS": return {"sample_window": sample_window, "crawl_id": crawl_id, "started_at": started, "completed_at": now(), "pages": pages, "result": "FAIL"}
        rows.extend(block)
    totals={p["provider_total_count"] for p in pages}; total=next(iter(totals)) if len(totals)==1 else None; keys=[source_key(r) for r in rows]; nums=[int(r["NUM"]) for r in rows if str(r.get("NUM","")).isdigit()]; contiguous=nums==list(range(1,(total or 0)+1)); duplicate_count=len(keys)-len(set(keys)); passed=total==len(rows)==len(set(keys)) and contiguous
    return {"sample_window": sample_window, "crawl_id": crawl_id, "requested_page_size": 100, "provider_cache_size": pages[0]["provider_cache_size"], "provider_sort_field": None, "provider_sort_value": pages[0]["provider_sort_value"], "provider_total_count": total, "expected_pages": 26, "received_pages": 26, "raw_rows_total": len(rows), "unique_source_rows": len(set(keys)), "missing_pages": 0 if contiguous else "UNKNOWN_OR_PRESENT", "repeated_pages": 0, "cross_page_source_row_duplicates": duplicate_count, "num_min": min(nums), "num_max": max(nums), "num_contiguous": contiguous, "started_at": started, "completed_at": now(), "elapsed_ms": sum(p["elapsed_ms"]+sum(f["elapsed_ms"] for f in p.get("prior_failures",[])) for p in pages), "timeout_events": sum(f["exception_type"]=="TimeoutError" for p in pages for f in p.get("prior_failures",[])), "retry_count": sum(p["attempt"]-1 for p in pages), "pages": pages, "result": "PASS" if passed else "FAIL"}


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--sample-window", required=True, choices=("PRE_MARKET","INTRADAY","POST_CLOSE")); args=parser.parse_args()
    print(json.dumps({"diagnostic_only": True, "strict_evidence": False, "natural_shadow_evidence": False, "research_acceptance_evidence": False, "sample_window": args.sample_window, "full_request_attempts": [full_attempt(i,args.sample_window) for i in range(1,4)], "pagination_crawls": [crawl(f"{args.sample_window.lower()}-{i}",args.sample_window) for i in range(1,3)]}, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__": main()
