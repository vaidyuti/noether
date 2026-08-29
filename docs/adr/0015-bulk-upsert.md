# 0015 — Bulk upsert: idempotent batch import

**Status:** Accepted

## Context

Chart-of-accounts and unit definitions arrive from external systems (domain
plugs, migration scripts, spreadsheets). A plain `POST` collection endpoint
makes those imports non-repeatable: re-running the script duplicates rows or
explodes on uniqueness. Operators need an import that is safe to run twice.

## Decision

Add `NoetherUpsertMixin` in `noether/api/viewsets/base.py`, exposing
`POST /<collection>/upsert/` with body `{"datapoints": [ ... ]}`.

### Identity rule

A datapoint identifies an existing row by **`slug`** when the target model
actually has a `slug` field; otherwise by **`id`** (the `external_id` UUID).
The field is feature-detected at request time via Django's `_meta.get_field`,
so a model that gains a `slug` later gets slug-based identity with no code
change here.

- No identifier present → **create**.
- Identifier present but no row matches (including a malformed UUID) →
  **create**, not 404. Creating is what makes re-import idempotent and is the
  entire point of a stable slug: the client asserts desired state, the server
  reconciles it.
- Two datapoints in one batch resolving to the same identity → the whole
  batch is rejected with 400 before any write. Silently letting the second win
  would make the result order-dependent and hide client bugs.

### Batching

The whole batch runs inside a single `transaction.atomic()` and is
all-or-nothing. If any datapoint fails validation or authorization, everything
rolls back and the response is HTTP 400 carrying a per-datapoint result array:
successful items rendered as they would have been, failed items carrying their
error body. The client sees exactly which rows failed. Genuinely unexpected
exceptions (anything the noether exception handler does not recognise) are
re-raised rather than flattened into a 400, so bugs stay loud.

Batch size is bounded by `MAX_DATAPOINTS_PER_UPSERT` (default 100,
env-configurable per ADR-0008 / 12-factor).

### Which viewsets get it

`AccountViewSet` and `UnitViewSet` — chart-of-accounts import is the real use
case.

**Transactions are deliberately excluded.** Per ADR-0001 a posted transaction
is immutable and is corrected only by a reversal. An "upsert" over
transactions would either be a no-op-with-extra-steps or would imply mutating
posted history, which the kernel forbids. Bulk transaction ingest, if ever
needed, belongs in a create-only batch endpoint with explicit idempotency
keys — not in this mixin.

## Consequences

- Imports become re-runnable; the second run is a no-op update.
- Authorization is unchanged: `handle_create` / `handle_update` are reused
  verbatim, so `authorize_create` / `authorize_update` run per datapoint. An
  unauthorized user cannot sneak a write through the batch endpoint.
- All-or-nothing means one bad row blocks a large import; the per-datapoint
  error array keeps that diagnosable.
- Plugs may apply the mixin to their own viewsets (exported in
  docs/domains/public-api.md).
