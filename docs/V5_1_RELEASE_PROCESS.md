# V5.1 Release Process

`python scripts/build_v5_1_release.py` creates a deterministic, secret-free,
self-contained `V5_1_RELEASE_CANDIDATE_UNFROZEN.zip`. It contains `shared_core`,
`v5_1`, V5.1 tests, configuration schema, dependency lock, release manifest and
SHA-256 manifest. Data, caches, logs, tokens, environment files and secrets are
excluded.

Extract the artifact into a clean directory and run:

```text
python -m v5_1.production_acceptance --release-root <directory> --release-only
```

Every blocking offline gate must report PASS and exit zero. Running without
`--release-only` also evaluates production-exit gates and must remain non-zero
until natural shadow, real Scheduler audit, single-writer ownership, rollback
drill and cutover authorization pass.

V5.1-RC1 is immutable but invalidated by the 2026-09-02 SSE Security Master
data-contract incident. It must never be rebuilt in place. The RC2 candidate may
be frozen only after the 44-group diagnostic, canonicalization contract,
targeted/full tests, dependency/import scan and clean-room acceptance all pass.
Any subsequent core data, runtime, execution, ledger, acceptance or Scheduler
change invalidates that candidate and requires a new release identity. Natural
window evidence remains zero and cannot be backfilled.
