# REST API Conventions & Surface (v1)

Base path: `/api/v1/`. JWT auth (`Authorization: Bearer *** OpenAPI at
`/api/schema/` (drf-spectacular). All resources addressed by `external_id`
(UUID), and slugged resources additionally by `slug`. Nested routing under
ledgers via drf-nested-routers.

## Addressing

Every detail route accepts **either** the resource's `external_id` (UUID) or,
for slugged resources, its `slug`. Resolution happens once, in the shared
viewset base (`NoetherBaseViewSet.get_object` / `LedgerScopedMixin.get_ledger`):

1. path segment parses as a UUID → `external_id` lookup;
2. otherwise, if the model is a `SluggedModel` → `slug` lookup, scoped by the
   viewset's already-narrowed queryset;
3. otherwise → 404 `object_not_found`.

Slugged today: `Ledger` (globally unique slug) and `Account` (slug unique
within its ledger). `Unit` is addressed by UUID (its `symbol` is a separate
per-ledger handle used in payloads, not in paths); `Transaction` has no slug.

```bash
GET /api/v1/ledgers/my-ledger/accounts/cash-in-hand/     # slug + slug
GET /api/v1/ledgers/9f1c…/accounts/3ab7…/                 # UUID + UUID
GET /api/v1/ledgers/my-ledger/accounts/3ab7…/balance      # mixed is fine
```

Slugs are optional on create (omit → `null`; never auto-generated) and mutable
via PATCH — renaming is a client-visible identity change that breaks importers
keyed on the old slug. A duplicate slug within its scope returns **400**
(`{"type": "validation_error", "msg": "slug '…' is already taken in this scope"}`);
a malformed slug returns **400** with the pydantic error shape. Full rules:
`docs/concepts/06-slugs.md`, ADR-0014.

## Conventions

- pydantic specs (`NoetherResource`) do serialization/deserialization;
  viewsets extend `NoetherBaseViewSet` (mixin lifecycle:
  `clean_data → model_validate → validate_data → authorize_* →
  de_serialize → perform_*`).
- Errors: `{"errors": [{"type": …, "msg": …}]}`; pydantic errors pass
  through as `{"errors": [...]}` (400); not-found → 404 with
  `object_not_found`; authz failure inside an accessible ledger → 403;
  ledger not accessible → 404 (no existence leak).
- Amounts are JSON **strings** in responses ("500.00"); requests accept
  string or number.
- Pagination: limit/offset, default 100.
- Timestamps: ISO-8601, timezone-aware, UTC canonical.

## Surface

```
# Domains (read-only registry introspection)
GET  /api/v1/domains/                    # registered domains
GET  /api/v1/domains/{slug}/             # incl. account_types, chart templates

# Ledgers
GET/POST      /api/v1/ledgers/           # POST: {domain, name, slug?, chart_template?}
GET/PUT/PATCH /api/v1/ledgers/{id}/
DELETE        /api/v1/ledgers/{id}/      # soft delete; Owner only

# Membership (RBAC)
GET/POST      /api/v1/ledgers/{id}/members/        # POST: {user, role}
PUT/DELETE    /api/v1/ledgers/{id}/members/{id}/
GET           /api/v1/roles/                       # built-in + plug roles

# Units
GET/POST      /api/v1/ledgers/{id}/units/
POST          /api/v1/ledgers/{id}/units/upsert/   # bulk idempotent import (ADR-0015)
GET/PUT/PATCH /api/v1/ledgers/{id}/units/{id}/     # precision immutable once used

# Tag configs (ADR-0013)
GET/POST      /api/v1/ledgers/{id}/tag-configs/
                  # POST: {display, resource, description?, status?, parent?,
                  #        exclusive_children?, metadata?}
GET/PUT/PATCH /api/v1/ledgers/{id}/tag-configs/{id}/
DELETE        /api/v1/ledgers/{id}/tag-configs/{id}/   # soft delete

# Accounts
GET/POST      /api/v1/ledgers/{id}/accounts/       # ?parent=&type=&archived=
                  # POST accepts optional {slug}; {id} may be a UUID or slug
POST          /api/v1/ledgers/{id}/accounts/upsert/ # bulk idempotent import (ADR-0015)
GET/PUT/PATCH /api/v1/ledgers/{id}/accounts/{id}/
POST          /api/v1/ledgers/{id}/accounts/{id}/archive
GET           /api/v1/ledgers/{id}/accounts/{id}/balance
                  # ?as_of=<iso>&value_in=<unit-symbol>
GET           /api/v1/ledgers/{id}/accounts/{id}/entries   # paginated

# Transactions
GET/POST      /api/v1/ledgers/{id}/transactions/
                  # POST body: {description, occurred_at, entries: [
                  #   {account, direction, amount, metadata?}], post?: bool}
                  # ?status=&account=&occurred_after=&occurred_before=
                  # ?tags=<tag-uuid>[,<tag-uuid>]   # row carries ANY of them
                  # ?tags_all=<tag-uuid>[,…]        # row carries ALL of them
GET/PUT/PATCH /api/v1/ledgers/{id}/transactions/{id}/   # drafts only (409 otherwise)
DELETE        /api/v1/ledgers/{id}/transactions/{id}/   # drafts only (hard delete)
POST          /api/v1/ledgers/{id}/transactions/{id}/post
POST          /api/v1/ledgers/{id}/transactions/{id}/reverse
                  # body: {description?, occurred_at?}
POST          /api/v1/ledgers/{id}/transactions/{id}/set-tag
POST          /api/v1/ledgers/{id}/transactions/{id}/unset-tag
                  # body: {tags: [<tag-config-uuid>, …]}; allowed on POSTED
                  # transactions (ADR-0013). 400 on unknown/duplicate/absent
                  # tag or exclusivity conflict; 403 without tag__apply.

# Prices (valuation overlay)
GET/POST      /api/v1/ledgers/{id}/prices/
                  # ?unit=&quote_unit=&as_of_before=&as_of_after=
```

## Bulk upsert (ADR-0015)

`POST /api/v1/ledgers/{id}/<collection>/upsert/` performs an idempotent
create-or-update over a batch of datapoints. Available on **accounts** and
**units**. Deliberately NOT available on transactions: posted transactions are
immutable (ADR-0001), so a bulk "update" of them is semantically wrong.

### Request

```json
{"datapoints": [ {...}, {...} ]}
```

Each datapoint is the same object body the collection's `POST` (create) or
`PUT`/`PATCH` (update) accepts.

### Identity resolution

| Condition | Behaviour |
| --- | --- |
| target model has a `slug` field and datapoint has `slug` | look up by `slug` |
| otherwise, datapoint has `id` | look up by `id` (`external_id`) |
| neither | create |
| identifier present, no row matches | **create, keeping the supplied `id`** — never 404 |
| `id` present but not a valid UUIDv7 | **400** |

The last two rows supersede ADR-0015 (see [ADR-0016](../adr/0016-client-supplied-uuidv7-external-ids.md)):
an unmatched `id` is retained rather than replaced with a fresh one, so re-running
an import converges; a malformed `id` is rejected rather than silently treated as
a create, because discarding an idempotency key turns a retry into a duplicate.

The slug field is feature-detected per request, so models that gain a `slug`
later automatically switch to slug identity.

### Response

- **200** — every datapoint succeeded. Body is a JSON array of the rendered
  rows, in request order.
- **400** — at least one datapoint failed. **The entire batch is rolled back**
  (single `transaction.atomic()`); nothing is written. The body is the same
  positional array, with successful entries rendered and failed entries
  carrying their error object, so the client can see exactly which rows failed.

### Error semantics

| Case | Result |
| --- | --- |
| body is not a JSON object | 400 `Invalid request body: expected an object` |
| `datapoints` is not a list | 400 `'datapoints' must be a list` |
| `datapoints` empty / missing | 400 `No datapoints provided` |
| a datapoint is not an object | 400 `Each datapoint must be an object` |
| more than `MAX_DATAPOINTS_PER_UPSERT` items (default 100, env-configurable) | 400 `Too many datapoints provided` |
| two datapoints resolve to the same identity | 400 `Duplicate identifier in batch: ...` (nothing written) |
| caller lacks write permission | 403-shaped `permission_denied` error inside the 400 result array; batch rolled back |
| unexpected server error | propagates as a normal 500 — never swallowed into a 400 |

Authorization runs per datapoint exactly as for single create/update: the
mixin reuses `handle_create` / `handle_update`.

### Worked example — importing a chart of accounts twice

```bash
LEDGER=8f2c...; API=http://localhost:8000/api/v1
AUTH="$NOETHER_AUTH_HEADER"   # e.g. the standard JWT Authorization header

cat > chart.json <<'EOF'
{"datapoints": [
  {"name": "Cash",    "account_type": "asset",   "unit": "0f1e...-unit-uuid"},
  {"name": "Revenue", "account_type": "revenue", "unit": "0f1e...-unit-uuid"}
]}
EOF

# First run — both rows are created
curl -sS -X POST "$API/ledgers/$LEDGER/accounts/upsert/" \
     -H "$AUTH" -H 'Content-Type: application/json' \
     -d @chart.json
# 200
# [{"id":"aaaa-...","name":"Cash","account_type":"asset",...},
#  {"id":"bbbb-...","name":"Revenue","account_type":"revenue",...}]

# Second run — feed back the ids (or, on a model with slugs, the same slugs).
# Both rows are UPDATED in place; no duplicates are created.
curl -sS -X POST "$API/ledgers/$LEDGER/accounts/upsert/" \
     -H "$AUTH" -H 'Content-Type: application/json' \
     -d '{"datapoints": [
           {"id": "aaaa-...", "name": "Cash"},
           {"id": "bbbb-...", "name": "Revenue"}
         ]}'
# 200 — same two ids returned; GET /accounts/ still shows exactly two rows.
```

## Filtering convention

List endpoints filter via **django-filter** `FilterSet` classes declared next to each
viewset (`filterset_class` + `DjangoFilterBackend`). Query param names
above are frozen public contract. UUID params filter on `external_id` FK lookups;
datetime params (`occurred_after/before`, `as_of_after/before`) are ISO 8601 and
validated by the FilterSet — invalid UUID/datetime values return **400**; invalid
boolean values (e.g. `archived=maybe`) are ignored per django-filter's BooleanFilter.
`as_of`/`value_in` on the balance endpoint are computation params, not queryset filters.

## Status code rules for lifecycle violations

- Editing/deleting a posted or reversed transaction: **409 Conflict**
  (`{"type": "immutable_transaction"}`).
- Posting an unbalanced transaction: **400**
  (`{"type": "conservation_error", "msg": "unit INR: debits 500.00 != credits 400.00"}`).
- Re-posting, re-reversing: **409**.
- Domain validator rejection: **400** (`{"type": "domain_validation_error"}`).
- Create replaying a known `id` with a conflicting body: **409**
  (`{"type": "id_conflict"}`).
- Create using an `id` already held by a row outside the caller's scope: **409**
  (`{"type": "id_unavailable"}`).

## Client-supplied IDs (ADR-0016)

`external_id` is a **UUIDv7** — time-ordered, so inserts stay at the tail of the
index as tables grow. The id space is v7-only: **any other UUID version is
rejected with a 400** on write. There is no v4 fallback.

Any create endpoint accepts an optional `id` in the body. Supply one and it
becomes the row's `external_id`; omit it and the server mints one. Because the
identifier is chosen before the request is sent, **it doubles as the idempotency
key** — reuse the same `id` when retrying an ambiguous failure:

| Condition | Result |
| --- | --- |
| `id` absent, `null`, or `""` | 201, server mints a UUIDv7 |
| `id` unused | 201, row created with that `id` |
| `id` known, request renders to the same row | **200** with the stored row (retry is a no-op) |
| `id` known, request renders to something else | **409** `id_conflict` |
| `id` held by a row the caller cannot see | **409** `id_unavailable` |
| `id` is a valid UUID but not version 7 | **400** |
| `id` is not a valid UUID | **400** |

Comparison is on the rendered resource, so field order, omitted defaults, and
equal-but-differently-written decimals (`100.00` vs `100.0000000000`) do not
cause spurious conflicts.

Clients should therefore treat any **2xx** as success on create, not `201`
specifically. `id` remains rejected on update — corrections go through the
documented lifecycle, not by rewriting identity.
