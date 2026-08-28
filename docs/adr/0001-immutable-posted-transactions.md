# ADR-0001: Immutable posted transactions; reversal-only corrections

- Status: Accepted
- Date: 2026-08-27
- Deciders: Rithvik Nishad

## Context

A conservation ledger's value is that its history is trustworthy. If posted
transactions can be edited or deleted, balances, snapshots, audit trails,
and caches all become invalidatable at any moment, and "what was the balance
on date X" becomes unanswerable.

## Decision

1. Transactions have a lifecycle: `draft → posted → reversed`.
2. A **posted** transaction and its entries are immutable: no field updates,
   no entry changes, no deletion (not even soft-delete).
3. Corrections are made by **reversal**: a new posted transaction with
   mirrored entries (debit↔credit swapped), linked via
   `reverses` / `reversed_by` FKs. The original's status becomes `reversed`
   (its entries still count toward history; the mirror cancels them).
4. A transaction may be reversed at most once. A reversal transaction may
   itself be reversed (explicitly re-instating the effect).
5. Drafts are fully mutable and hard-deletable; they never affect balances.

## Consequences

- (+) Balances, snapshots, and point-in-time queries are append-only folds —
  cacheable and auditable forever.
- (+) The API surface for posted transactions is tiny: `reverse` only.
- (−) Fixing a typo in a posted transaction takes two transactions
  (reverse + repost). UIs should offer a one-click "reverse & edit copy".
- (n) `occurred_at` of a reversal defaults to the reversal time, but MAY be
  set to the original's `occurred_at` for same-period correction; both are
  legitimate, chosen by the caller.

## Alternatives considered

- **Mutable with audit log** (Care's general pattern): rejected — audit logs
  record that history changed; ledgers must guarantee it cannot.
- **Delete + repost**: rejected — breaks referential integrity of external
  references (receipts, meter readings) and point-in-time replay.
