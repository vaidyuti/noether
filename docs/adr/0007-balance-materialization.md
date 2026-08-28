# ADR-0007: Materialized balances + snapshots + integrity verifier

- Status: Accepted
- Date: 2026-08-27
- Deciders: Rithvik Nishad

## Context

Balance reads are the hottest path; entries are the only source of truth;
posted history is immutable (ADR-0001), making balances pure folds.

## Decision

1. **Source of truth**: `balance(account, t) = Σdebits − Σcredits` over
   posted entries with `occurred_at ≤ t`. (Note: current balance uses ALL
   posted entries; point-in-time queries fold by `occurred_at`.)
2. **AccountBalance** (one row per account) is maintained synchronously
   inside the posting DB transaction. Affected rows are locked with
   `select_for_update(ordered by account_id)` to serialize concurrent posts
   and avoid deadlocks.
3. **BalanceSnapshot** rows `(account, as_of, balance)` are written by a
   periodic Celery task. Point-in-time balance = nearest snapshot ≤ t +
   replay of the gap. Snapshot cadence is a deployment setting.
4. **Integrity verifier** (Celery, periodic): re-derives balances from
   entries, compares to `AccountBalance`, verifies per-transaction
   conservation, and raises alerts (log + configurable webhook) on drift.
   Drift is a bug, never auto-healed silently.
5. Reversals restore balances by ordinary application of the mirror
   entries — no special-cased balance math anywhere.

## Consequences

- (+) O(1) current-balance reads; O(gap) historical reads.
- (+) The verifier is the operational embodiment of the conservation law.
- (−) Posting throughput serializes on hot accounts; acceptable for the
  target scale, revisit with per-account sharded counters only if proven
  necessary (superseding ADR required).

## Alternatives considered

- Compute balances on every read: rejected — O(entries) on the hot path.
- Async balance updates (post-commit Celery): rejected — read-your-write
  inconsistency immediately after posting is unacceptable UX.
- Event sourcing with projections: the design IS event sourcing in spirit;
  full ES frameworks add ceremony without benefit here.
