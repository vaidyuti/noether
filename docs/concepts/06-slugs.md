# Slugs — human-readable, scope-unique addresses

## Why

Two problems, one mechanism:

1. **Idempotent bulk import.** An importer that re-runs the same source data
   must not duplicate rows. With a slug carried by the source record, the
   importer has a natural upsert key that it owns — no UUID round-trip, no
   local id map to persist between runs.
2. **Addressability from plain curl.** `GET /api/v1/ledgers/my-ledger/accounts/cash-in-hand/`
   works without first looking up two UUIDs.

## Which models have slugs

| Model | Slug | Uniqueness scope |
| --- | --- | --- |
| `Ledger` | yes | global (`SLUG_SCOPE_FIELDS = ()`) |
| `Account` | yes | per ledger (`SLUG_SCOPE_FIELDS = ("ledger",)`) |
| `Unit` | no — `symbol` already plays this role | (`ledger`, `symbol`) |
| `Transaction` | no — transactions are events, not addressable nouns | — |

## Format rules

```
^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$      max length 100
```

- lowercase alphanumerics only; **uppercase is rejected** (a slug must have
  exactly one spelling, so case-folding at read time is not enough).
- `-` and `_` allowed as **internal** separators only: may not lead or trail.
- no whitespace, no dots, no slashes (a slug is one path segment).
- max **100** characters — long enough for deep human paths
  (`operating-expenses-utilities-electricity`), short enough to stay a cheap
  btree index entry.

A single-character slug (`a`) is valid; the empty string is not.

The grammar is enforced **twice**, deliberately:

- pydantic spec level (`SlugStr` in `noether.resources.base`) → clean 400 with
  the pydantic error shape, before anything touches the DB;
- model level (`validate_slug` field validator + `SluggedModel.save()`) → any
  write path, including services and plug code that bypasses the REST layer.

## Scoping model

`SluggedModel` is an abstract mixin. It contributes the nullable `slug` column
and a scope declaration; the concrete model contributes the matching
constraint:

```python
class Account(SluggedModel, NoetherBaseModel):
    SLUG_SCOPE_FIELDS = ("ledger",)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ledger", "slug"], name="unique_account_slug_per_ledger"
            ),
        ]
```

`SluggedModel.save()` pre-checks the same scope in Python so callers get a
readable `ValidationError` (→ 400) rather than an `IntegrityError` (→ 500);
the DB constraint remains the actual guarantee under concurrency.

## Optionality — slugs are OPTIONAL, never auto-generated

Omitting `slug` on create stores `NULL`. We deliberately do **not** derive a
slug from `name`: two accounts legitimately named "Cash" would silently
collide, and the failure would surface at import time in a form the operator
never asked for. A slug is an explicit assertion of a stable external name.

Postgres treats `NULL`s as distinct in a unique index, which is exactly the
behaviour we want: any number of accounts in one ledger may have no slug.
This is covered by test (`test_null_slugs_do_not_collide`).

## Mutability — slugs ARE updatable, and that is an identity change

`PATCH {"slug": "petty-cash"}` is allowed. The consequence must be understood:

- the old URL immediately 404s; the object keeps its `external_id` forever.
- an importer keyed on the old slug will treat the row as missing and
  **create a new one** on its next run.

Therefore: `external_id` is the permanent identity; the slug is a mutable
*alias*. Importers that need absolute stability should record the returned
`id` (UUID) alongside their own key. Renaming a slug is an operator action,
not a routine one.

## Addressing — resolution rule

The shared viewset base resolves the URL path segment in one place
(`NoetherBaseViewSet.get_object`, plus `LedgerScopedMixin.get_ledger` for the
nested ledger segment):

1. if the value parses as a UUID → look up `external_id`;
2. else, if the model is a `SluggedModel` → look up `slug`;
3. else → 404.

Slug lookup is automatically scope-safe because `get_queryset()` is already
narrowed (accounts are filtered to the resolved ledger), so a slug can never
resolve across a scope boundary.

Corollary: a slug that happens to be a valid UUID string is *storable* but not
*addressable by slug* — rule 1 wins. Don't do that.

## Worked examples

```bash
# create a ledger with a slug
curl -X POST /api/v1/ledgers/ -H 'Content-Type: application/json' \
  -d '{"domain": "finance", "name": "My Books", "slug": "my-ledger"}'

# create an account with a slug
curl -X POST /api/v1/ledgers/my-ledger/accounts/ -H 'Content-Type: application/json' \
  -d '{"name": "Cash In Hand", "slug": "cash-in-hand",
       "account_type": "asset", "unit": "<unit-uuid>"}'

# these two are the same object
curl /api/v1/ledgers/my-ledger/accounts/cash-in-hand/
curl /api/v1/ledgers/9f1c.../accounts/3ab7.../

# mixing forms is fine
curl /api/v1/ledgers/my-ledger/accounts/3ab7.../balance

# rename (identity change — old URL now 404s)
curl -X PATCH /api/v1/ledgers/my-ledger/accounts/cash-in-hand/ \
  -d '{"slug": "petty-cash"}'

# duplicate in the same scope
curl -X POST /api/v1/ledgers/my-ledger/accounts/ -d '{"slug": "cash-in-hand", ...}'
# 400 {"errors": [{"type": "validation_error",
#                  "msg": "slug 'cash-in-hand' is already taken in this scope"}]}
```

The same slug in a *different* ledger is fine — that is the point of scoping.

See ADR-0014 for the decision record.
