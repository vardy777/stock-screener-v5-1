# V5.1-RC2 SSE Duplicate Analysis — 2026-09-02

## Result

The 44 RC1 duplicate-symbol groups are fully explained as SSE A/B
security-category variants:

- every group contains exactly two rows;
- one row has `STOCK_TYPE=1` (A share);
- one row has `STOCK_TYPE=2` (B share);
- both rows expose the same `A_STOCK_CODE` and company identity;
- both rows expose a corresponding `B_STOCK_CODE` beginning with `9`;
- category-specific security name and listing date differ;
- the RC1 parser discarded `STOCK_TYPE` before uniqueness validation and thus
  treated both category rows as separate A-share identities.

Classification summary:

| Classification | Groups |
|---|---:|
| `CATEGORY_VARIANT` | 44 |
| `UNKNOWN` | 0 |
| `GENUINE_CURRENT_IDENTITY_CONFLICT` | 0 |

`duplicate_groups_analyzed = 44`

`unexplained_groups = 0`

## Incident shape

- SSE raw records: 2,516
- RC1 valid parsed rows: 2,506
- RC1 unique symbols: 2,462
- duplicate groups: 44
- duplicate surplus: 44
- expected canonical records under the frozen category rule: 2,462

The number 2,462 is an incident-response result for this exact response. It is
not a permanent hard-coded expected universe size.

SZSE independently returned 2,899 records and 2,899 unique symbols.

## Canonicalization decision

For a group matching the complete frozen `CATEGORY_VARIANT` predicate, select
the sole `STOCK_TYPE=1` record as the current A-share identity and retain the
`STOCK_TYPE=2` record in diagnostic lineage. The decision is based on the SSE
official category field, not row order.

Any missing category, multiple A rows, multiple B rows not covered by the
contract, inconsistent company/status data, invalid B code or other new shape
is not canonicalized and fails closed.

## Evidence

Machine-readable per-group evidence:

`docs/reports/artifacts/V5_1_RC2_SSE_DUPLICATE_CLASSIFICATION_2026-09-02.json`

The artifact records each symbol, relevant raw fields, source-row identifiers,
classification, decision and reason. It is generated from the official SSE
response and contains no token or environment secret.

Observed response SHA-256:

`0b980fb8cabff9cbba6980a4c5a5a4539767d8c227f5affa1962729ff554cbbe`

## Root cause

`SSE records -> RC1 generic _record -> category erased -> duplicate A_STOCK_CODE
-> combined official uniqueness assertion`

The request and parse succeeded. The failure is a source-schema modeling bug,
not an empty directory and not an Eastmoney, quote, strategy or execution fault.

## Gate

`44 DUPLICATE GROUPS FULLY CLASSIFIED = YES`

`UNEXPLAINED GROUPS = 0`

This analysis does not authorize production cutover or claim strategy
effectiveness.
