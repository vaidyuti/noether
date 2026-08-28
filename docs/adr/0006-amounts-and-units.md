# ADR-0006: Decimal amounts, opaque per-ledger units, per-unit balancing

- Status: Accepted
- Date: 2026-08-27
- Deciders: Rithvik Nishad

## Context

The kernel must represent money (2 dp), energy (arbitrary dp), stock
quantities (fractional units), etc., without floating-point error and
without knowing what any unit means.

## Decision

1. Amounts are `Decimal`, stored as `DecimalField(max_digits=30,
   decimal_places=10)`. Floats are forbidden across the entire codebase
   (API accepts JSON strings or numbers, pydantic coerces to Decimal;
   serialization emits strings).
2. `Unit` is a per-ledger row: `symbol`, `name`, `precision (0–10)`,
   `metadata`. Core performs **no arithmetic across units** and no
   conversions.
3. Every entry's amount MUST be a multiple of `10^-precision` of its
   account's unit — validated at entry creation and again at post.
4. Entry amounts are strictly positive; direction lives in the
   `direction` enum. Balancing is checked **per unit** within a
   transaction.
5. Signed balance convention: `balance = Σdebits − Σcredits`. Presentation
   sign (whether credit-normal accounts display negated) is a domain/UI
   concern.
6. Units are ledger-scoped (not global): two ledgers' `INR` are distinct
   rows. Domains seed standard units via chart templates.

## Consequences

- (+) Exact conservation checks (`==` on Decimal), no epsilon tolerances.
- (+) A stock ticker, a currency, and kWh are the same kind of thing.
- (−) No global unit registry means cross-ledger reporting must map by
  symbol; acceptable — ledgers are isolated authorization boundaries anyway.

## Alternatives considered

- Integer minor-units (cents): rejected — per-unit precision varies and
  10-dp Decimal covers crypto/energy fractions uniformly.
- Global unit table: rejected — forces cross-domain governance of symbols
  and breaks ledger isolation.
