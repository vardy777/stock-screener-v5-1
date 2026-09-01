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

The current artifact is deliberately `UNFROZEN`: the worktree is dirty and no
RC is declared. After independent approval, a clean exact commit may become RC1.
Any core data, runtime, execution, ledger, acceptance or Scheduler change then
invalidates that RC and resets natural-window evidence.
