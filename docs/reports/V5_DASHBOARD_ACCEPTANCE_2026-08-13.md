# V5 single-page dashboard acceptance — 2026-08-13

## Product contract

- One stock-research page, not separate beginner/research/operations or four-tab views.
- The first screen states today's conclusion and the action the user should take.
- The same page contains recommendation or explicit empty reason, risks, execution rules, paper account and evidence conclusion.
- Morning candidates are observation-only and show no buy price.
- A confirmed candidate may show only its frozen 14:49 ask reference. The next-session exit price is never predicted.
- The dashboard remains read-only, `research_locked`, and disconnected from brokers.

## Evidence

- Real browser DOM inspection showed the expected single-page section order and correct Chinese text.
- Responsive geometry at 390 px had no horizontal overflow; content width was 351 px inside a 390 px viewport.
- API and page both projected the same V5 read model.
- Focused product tests: 20 passed.
- Full repository suite: 284 passed.

## Deployment status

- Updated preview is running at `http://127.0.0.1:8899/`.
- Port 8898 remains the V4 rollback dashboard until the V5 live shadow window and notification lineage pass. This acceptance does not authorize a premature production switch.
