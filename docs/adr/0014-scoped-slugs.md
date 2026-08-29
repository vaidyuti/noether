# ADR-0014: Scoped unique slugs on Ledger and Account

**Status**: Accepted

## Context

Bulk importers re-run against the same source data and must be idempotent:
re-importing must update, not duplicate. Without a client-ownable key, an
importer has to persist a local mapping from source record → noether UUID,
which is fragile and makes one-shot `curl` workflows impossible.

Separately, addressing every object by UUID makes the API hostile to manual
use: reading one account's balance requires two prior lookups.

We need a human-readable, client-assigned, stable-enough external name.

## Decision

Add an **optional, nullable `slug`** to `Ledger` and `Account` only, uniquely
constrained over a **declarable scope**.

- `SluggedModel` abstract mixin (`noether.ledger.models_base`) contributes the
  `slug` column, the format validator, and `SLUG_SCOPE_FIELDS: tuple[str, ...]`.
- The concrete model declares the matching
  `UniqueConstraint(fields=[*SLUG_SCOPE_FIELDS, "slug"])`.
  - `Ledger`: scope `()` → globally unique (`unique_ledger_slug`).
  - `Account`: scope `("ledger",)` → unique per ledger
    (`unique_account_slug_per_ledger`).
- Grammar: `^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$`, max 100 chars; enforced in the
  pydantic spec (`SlugStr`) and at the model layer.
- Slugs are **optional** (NULL when omitted) and never auto-generated.
- Slugs are **mutable** via PATCH; this is a documented identity change.
- Lookup resolution lives in exactly one place — `NoetherBaseViewSet.get_object`
  and `LedgerScopedMixin.get_ledger`: UUID-parsable → `external_id`, else slug
  if the model is slugged, else 404.

Not slugged: `Unit` (its `symbol` already fills this role, unique per ledger)
and `Transaction` (an event, not an addressable noun; its natural external key
is a client `metadata` reference, not a URL segment).

## Alternatives considered

### Composite prefixed slug strings — REJECTED

A known pattern stores a single globally-unique string built by prefixing the
scope's UUID, e.g. `f-<parent-uuid>-<slug>`, and takes a plain
`unique=True` on that one column. Rejected because:

1. **The stored value is not the value.** Every read must strip the prefix and
   every write must reconstruct it; the column is unreadable in `psql` and in
   any downstream analytics.
2. **It fakes a composite key with string concatenation.** The database already
   has a first-class primitive for "unique within a scope" — a multi-column
   unique index. Encoding the scope into a string throws away the FK
   relationship, prevents the planner from using the scope column, and makes
   re-parenting a row a string-rewrite instead of an FK update.
3. **It hardcodes one scope shape.** The prefix pattern assumes exactly one
   scoping parent. `SLUG_SCOPE_FIELDS` is an n-tuple, so a plug can scope by
   two fields, or none, without new machinery.
4. **Length and escaping hazards.** The prefix eats budget from the max length,
   and a slug containing the separator makes the encoding ambiguous.

### Auto-generating a slug from `name` — REJECTED

Creates surprising collisions (two accounts named "Cash") and invents a
public identifier the client never asked for and cannot predict.

### Immutable slugs — REJECTED

Typos in a slug are inevitable during import bring-up; forcing a delete/recreate
to fix one is worse than documenting the rename consequence.

### Slug on every model — REJECTED

`Unit.symbol` is already the human handle. Slugging transactions invites
clients to treat events as mutable named entities.

## Consequences

- Importers get a stable upsert key they own; re-import is idempotent as long
  as slugs are not renamed.
- Renaming a slug breaks importer identity — documented in
  `docs/concepts/06-slugs.md`; `external_id` remains the permanent identity.
- Multiple NULL slugs coexist in a scope (Postgres NULL-distinct semantics),
  which is the intended "slug is optional" behaviour and is covered by test.
- `SluggedModel` and `validate_slug` are exported to plugs, so plug models get
  the same addressing semantics for free.
