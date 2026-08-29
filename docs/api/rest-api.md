# REST API Conventions & Surface (v1)

Base path: `/api/v1/`. JWT auth (`Authorization: Bearer …`). OpenAPI at
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
GET/PUT/PATCH /api/v1/ledgers/{id}/units/{id}/     # precision immutable once used

# Accounts
GET/POST      /api/v1/ledgers/{id}/accounts/       # ?parent=&type=&archived=
                  # POST accepts optional {slug}; {id} may be a UUID or slug
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
GET/PUT/PATCH /api/v1/ledgers/{id}/transactions/{id}/   # drafts only (409 otherwise)
DELETE        /api/v1/ledgers/{id}/transactions/{id}/   # drafts only (hard delete)
POST          /api/v1/ledgers/{id}/transactions/{id}/post
POST          /api/v1/ledgers/{id}/transactions/{id}/reverse
                  # body: {description?, occurred_at?}

# Prices (valuation overlay)
GET/POST      /api/v1/ledgers/{id}/prices/
                  # ?unit=&quote_unit=&as_of_before=&as_of_after=
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
