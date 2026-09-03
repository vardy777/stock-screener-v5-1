# V5.1 SSE Security Master Canonicalization Contract

Status: `FROZEN FOR V5.1-RC2 IMPLEMENTATION`

Contract ID: `v5.1-sse-master-canonicalization-v1`

Incident basis: the 2026-09-02 SSE official directory returned 2,516 raw
records. RC1 parsed 2,506 records but produced only 2,462 unique A-share
symbols because 44 A/B category pairs expose the same `A_STOCK_CODE`.

## 1. Scope and authority

The input is the raw response from the SSE official security directory. SSE and
SZSE remain the authoritative base for their respective exchanges. Eastmoney
remains an optional third-party cross-check and can never replace an unavailable
or invalid official source.

This contract changes only SSE identity canonicalization. It does not change
strategy, ranking, candidate selection, CloseScan, decision/execution windows,
position sizing, paper ledgers, acceptance, notifications, scheduler ownership,
port 8899 or V5 production ownership.

## 2. Strict input classification

Every raw SSE row is classified before it can become a current A-share identity.
The classifier reads, at minimum:

- `A_STOCK_CODE`, `B_STOCK_CODE`, `COMPANY_CODE`;
- `COMPANY_ABBR`, `FULL_NAME`, `SEC_NAME_FULL`;
- `LISTING_DATE` or `LIST_DATE`, `DELIST_DATE`;
- `STOCK_TYPE`, `LIST_BOARD`;
- `STATE_CODE`, `STATE_CODE_STOCK`, `PRODUCT_STATUS`;
- `NUM` as the source-row identifier.

`COMPANY_CODE` must not silently substitute for a missing or invalid
`A_STOCK_CODE`. A row without a valid six-digit SSE A-share code is outside the
current A-share identity stream and is reported as rejected input.

The known category values used by this contract are:

- `STOCK_TYPE=1`: A-share security-category row;
- `STOCK_TYPE=2`: B-share security-category row;
- other values: preserved only when the symbol is unique, matching RC1 scope;
  if involved in a duplicate group they are unknown and fail closed.

## 3. Grouping and canonical identity

Strictly parsed rows are grouped by `A_STOCK_CODE`. The canonical output contains
at most one current identity for each symbol.

### 3.1 Unique group

A group containing one valid row is preserved with its existing RC1 identity
semantics only when it is not already delisted as of the response retrieval
date. A valid `DELIST_DATE` on or before that date classifies the row as
historical/delisted and excludes it from the current identity stream while
retaining it in diagnostics.

### 3.2 Exact duplicate source row

Multiple rows may collapse only when all identity- and status-relevant fields
are equal after strict normalization. The canonical record is derived from the
common semantic content, never input order. All sorted source-row identifiers
must remain in diagnostic lineage.

Classification: `EXACT_DUPLICATE_SOURCE_ROW`.

### 3.3 SSE A/B category variant

A duplicate group is `CATEGORY_VARIANT` only when all conditions hold:

1. exactly one row has `STOCK_TYPE=1`;
2. every other row has `STOCK_TYPE=2`;
3. every row exposes the same valid `A_STOCK_CODE`;
4. every row exposes the same non-empty `B_STOCK_CODE` beginning with `9`;
5. company code, company abbreviation, full company name, board, delisting
   field and status fields agree across rows;
6. differences are restricted to share-category fields, share security name,
   category-specific listing date and source-row identifier.

The `STOCK_TYPE=1` row is the sole canonical A-share identity. Its listing date
and A-share security name semantics are used. The B-share row is excluded from
the A-share current identity stream but retained in classification diagnostics.

This is not arbitrary first-row selection: the choice is made by an explicit
official category field and is invariant to input ordering.

### 3.4 Historical/status and delisted rows

Historical, delisted or multiple-status rows are not allowed to compete as a
second current identity. A duplicate group is `CURRENT_PLUS_DELISTED` only when
exactly one row is current and every other row has an explicit, valid
`DELIST_DATE` no later than retrieval time. The sole current record is selected;
every delisted row remains in diagnostic lineage. More than one current row, an
invalid date or a row whose historical status cannot be proved is not covered by
this rule and fails closed.

The only lifecycle rule frozen here is this explicit official `DELIST_DATE`
comparison. An invalid non-empty delisting date is ambiguous and fails closed
with a structured diagnostic; it is never silently excluded or treated as
active. Any more
complex historical/status combination is `UNKNOWN` and fails closed. This
repair does not introduce a new bi-temporal history model.

## 4. Genuine conflict and unknown form

After classification, two or more rows that still claim to be the current
A-share identity for the same symbol and differ on any identity-defining field
are `GENUINE_CURRENT_IDENTITY_CONFLICT`.

Any duplicate shape not exactly covered by Sections 3.2 or 3.3 is `UNKNOWN`.

Both outcomes must raise `ContractViolation` with a structured SSE
canonicalization diagnostic. They must never use `drop_duplicates`, dict
overwrite, first-row-wins, last-row-wins, silent skip or Eastmoney fallback.

## 5. Determinism

For any permutation of identical input rows, including original, reverse,
sorted and seeded shuffle, the following semantic values must be identical:

- canonical record sequence;
- canonical record semantic serialization/hash;
- duplicate classification sequence;
- source-row lineage sequence;
- counts and conflict samples.

Retrieval timestamps and raw transport hashes are evidence metadata and are not
part of the canonical semantic comparison.

## 6. Diagnostics and causal errors

The source layer must distinguish:

- `OFFICIAL_SOURCE_UNAVAILABLE`;
- `OFFICIAL_SOURCE_HTTP_FAILURE`;
- `OFFICIAL_SOURCE_PARSE_FAILURE`;
- `OFFICIAL_SOURCE_EMPTY`;
- `SSE_CANONICALIZATION_FAILURE`;
- `DUPLICATE_SECURITY_IDENTITY`;
- `AMBIGUOUS_CURRENT_IDENTITY`.

A canonicalization diagnostic contains source, stage, endpoint, HTTP status,
raw response SHA-256, raw/parsed/canonical/unique counts, duplicate count,
classification counts, a bounded conflicting-symbol sample, exception type and
message. It must not contain tokens or the complete raw response in logs.

An HTTP request failure, an HTTP-200 parse failure, zero valid rows, a canonical
conflict and a later freshness rejection are different causes and must not be
collapsed into `official master empty`.

## 7. Evidence and total conservation

For each response, diagnostics must make this accounting verifiable:

`raw rows = canonical rows + category/history exclusions + invalid rows +
collapsed duplicate surplus + quarantined rows`

The raw response remains content-addressed by SHA-256. Duplicate classification
artifacts retain only identity-relevant source fields and hashes; sensitive
configuration and tokens are forbidden.

## 8. Failure and release policy

Any new duplicate form or ambiguity fails closed. No runtime heuristic may be
added to meet a market deadline. A required code change invalidates the current
release candidate and requires a new artifact, offline tests, clean-room
acceptance and freeze.

RC1 remains immutable and invalidated. Only a separately frozen RC2 may enter a
new Natural SHADOW sequence. `research_locked=true`, `broker_orders=false`,
`production_owner=V5` and `production_cutover_authorized=false` remain mandatory.

## Gate

`CANONICALIZATION CONTRACT = FROZEN`
