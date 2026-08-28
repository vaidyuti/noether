# ADR-0002: Valuation as computed overlay, not ledger entries

- Status: Accepted
- Date: 2026-08-27
- Deciders: Rithvik Nishad

## Context

Investments and priced commodities change value over time without any
physical/ownership flow occurring. The ledger must support "my portfolio is
worth ₹X today" without corrupting the principle that entries record facts.

## Decision

1. The kernel stores holdings as quantities in native units (shares, kWh) —
   see ADR-0006.
2. A `UnitPrice` append-only time series (`unit`, `quote_unit`, `price`,
   `as_of`, `source`) is kernel data; **strategies** that populate/interpret
   it are domain-plug concerns.
3. Market value and unrealized gains are **computed at read time**
   (`balance × price as_of t`); they are never posted as entries.
4. Realized gains post ordinary transactions at disposal time.
5. Cross-unit exchanges use the trading-accounts pattern
   (`docs/concepts/02-valuation.md`); per-unit conservation always holds.

## Consequences

- (+) Ledger entries remain pure facts; no synthetic mark-to-market noise.
- (+) Any unit pair can be valued (kWh→INR billing views) with one mechanism.
- (−) "Net worth over time" requires price-series joins at query time;
  mitigated by snapshots + price indexing, and domains may cache computed
  valuations OUTSIDE the ledger tables.
- (n) Cost-basis strategies (FIFO/average) are domain computations over
  kernel entries.

## Alternatives considered

- **Periodic revaluation postings** (GnuCash trading-account mark-to-market):
  rejected for core — pollutes history with synthetic events and forces a
  revaluation cadence. A domain plug MAY implement this on top as opt-in
  behavior; nothing in core prevents it.
