# Testing Standard (operational companion to ADR-0003)

## Commands

```bash
make test            # full suite + coverage gate (fail_under=100, branch)
make test path=noether.ledger.tests.unit
make lint            # ruff check + format --check
```

## The law

1. **No production code without a failing test first.** PRs are expected to
   show test commits/red-green history or be trivially auditable as TDD.
2. Coverage config (pyproject):
   ```toml
   [tool.coverage.run]
   branch = true
   source = ["noether"]
   omit = ["*/migrations/*", "manage.py", "config/wsgi.py", "config/asgi.py"]

   [tool.coverage.report]
   fail_under = 100
   show_missing = true
   ```
3. **MC/DC policy**: for every compound boolean expression, write one test
   per operand demonstrating that operand independently changes the
   outcome. Prefer decomposing compounds into guard clauses so branch
   coverage enforces this mechanically. Reviewers check this explicitly.
4. `# pragma: no cover` requires an entry in
   `docs/operations/coverage-exceptions.md` with justification.

## Required property-based suites (hypothesis)

| Property | Statement |
| --- | --- |
| Conservation | Random valid entry sets: post succeeds iff per-unit Σdebit == Σcredit |
| Balance fold | balance(account) == fold over its posted entries, for random transaction sequences |
| Reversal round-trip | post(T); reverse(T) ⇒ all balances equal pre-T state |
| Snapshot equivalence | balance via snapshot+replay == balance via full fold, for random snapshot points |
| Precision | amounts violating unit precision are always rejected |
| Immutability | any mutation attempt on posted T raises, state unchanged |

## Test data

factory-boy factories in `noether/ledger/tests/factories.py` are the shared
vocabulary (also exported to plugs). No raw `Model.objects.create` in tests
outside factories.

## Integration tier

`tests/integration/` runs against real Postgres + Redis (docker compose in
CI): posting concurrency (two simultaneous posts on one account), Celery
snapshot + verifier tasks end-to-end, JWT auth flow. No mocks in this tier
(user preference: real end-to-end verification).
