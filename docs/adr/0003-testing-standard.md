# ADR-0003: Testing standard — 100% branch coverage + MC/DC-by-policy

- Status: Accepted
- Date: 2026-08-27
- Deciders: Rithvik Nishad

## Context

Golden rule: TDD, 100% coverage from day 0, DO-178B-inspired (MC/DC).
Python tooling measures statement and branch coverage but not true MC/DC.

## Decision

1. **TDD is mandatory**: docs → failing test → implementation, per feature.
2. `coverage.py` with `branch = True` and `fail_under = 100`, enforced in CI
   and locally (`make test`). Applies to core and every plug.
3. **MC/DC-by-policy**: every compound boolean condition (two or more
   operands in `and`/`or`, including chained comparisons used as guards)
   MUST have tests where each operand independently flips the outcome.
   Enforced by code review checklist and by preferring
   guard-clause decomposition (one condition per branch) so branch coverage
   approximates MC/DC.
4. `# pragma: no cover` is **banned** except for lines listed with
   justification in `docs/operations/coverage-exceptions.md`
   (e.g. `if TYPE_CHECKING:`, `__repr__` used only in debugging is NOT
   exempt — write the test).
5. **Property-based tests (hypothesis)** are required for kernel invariants:
   conservation, balance≡fold(entries), reversal round-trip,
   snapshot-replay equivalence, precision validation.
6. Test taxonomy: `tests/unit/` (pure logic), `tests/api/` (viewset flows),
   `tests/properties/` (hypothesis), `tests/integration/`
   (Celery + Redis + Postgres flows).

## Consequences

- (+) The conservation guarantees are machine-checked, not aspirational.
- (−) Slower feature velocity; accepted deliberately.
- (n) True MC/DC certification tooling doesn't exist for Python; policy +
  branch-100 is the honest approximation, and this ADR records that
  explicitly.

## Alternatives considered

- Statement coverage only: rejected — misses untaken branches, the exact
  place conservation bugs hide.
- Mutation testing (mutmut) as gate: deferred — valuable but slow; may be
  added as a nightly job, not a merge gate.
