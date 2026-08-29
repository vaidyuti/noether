# Core Public API for Plugs

The ONLY core import surface plugs may use. Anything not listed here is
core-internal and may change without notice.

## Import surface

| Module | Exports | Purpose |
| --- | --- | --- |
| `noether.domains.registry` | `DomainRegistry` | `register(config)` (idempotent for identical configs, ADR-0011), `get(slug)`, `all()` |
| `noether.domains.config` | `DomainConfig`, `AccountTypeDef`, `UnitDef`, `ChartTemplate`, `ChartNode` | Domain declaration (incl. `urls` for plug routes) |
| `noether.domains.services` | `create_ledger(...)`, `instantiate_chart(...)` | Programmatic ledger/chart creation (same path as REST) |
| `noether.domains.validators` | `TransactionValidator` | Post-time validation hook base |
| `noether.domains.valuation` | `ValuationStrategy`, `PriceQuote` | Price feed hook base |
| `noether.ledger.exceptions` | `DomainValidationError`, `ConservationError`, `ImmutabilityError` | Raise/catch |
| `noether.ledger.models` | `Domain`, `Ledger`, `Unit`, `Account`, `Transaction`, `Entry`, `AccountBalance`, `UnitPrice` | FK targets & read access |
| `noether.ledger.models_base` | `SluggedModel`, `validate_slug`, `SLUG_PATTERN`, `SLUG_MAX_LENGTH`, `slug_or_uuid_filters` | Give a plug model a scope-unique slug (ADR-0014) |
| `noether.ledger.services.posting` | `create_transaction(...)`, `post_transaction(...)`, `reverse_transaction(...)` | THE only write path to the ledger |
| `noether.ledger.services.balances` | `get_balance(account, as_of=None)` (normalized), `get_raw_balance(account, as_of=None)`, `get_market_value(account, value_in, as_of=None)` | Read helpers |
| `noether.resources.base` | `NoetherResource`, `SlugStr`, `ExternalId` | pydantic spec base for plug APIs; `SlugStr` validates slug fields; `ExternalId` types UUID identifier fields |
| `noether.api.viewsets.base` | `NoetherBaseViewSet`, `NoetherModelViewSet`, `NoetherModelReadOnlyViewSet`, `LedgerScopedMixin`, `NoetherUpsertMixin` | Plug viewsets (`NoetherUpsertMixin` adds `POST /<collection>/upsert/`, ADR-0015) |
| `noether.tagging.models` | `TaggableMixin` | Give a plug model an ArrayField tag column (ADR-0013) |
| `noether.tagging.base` | `BaseTagManager`, `LedgerTagManager` | Apply/remove/render tags with scope, exclusivity and authz enforced |
| `noether.tagging.filters` | `TagFilter` | django-filter filter for a taggable queryset (`behavior="any"|"all"`) |
| `noether.ledger.resources.tag.constants` | `TagResource`, `TagStatus` | Taggable resource-type enum and config status |
| `noether.api.viewsets.tags` | `TagMixin` | Adds `set-tag`/`unset-tag` detail actions to a plug viewset |
| `noether.security.permissions.base` | `PermissionController`, `PermissionHandler` | Register plug permissions |
| `noether.security.roles.role` | `Role`, `RoleController` | Register plug roles |
| `noether.security.authorization.base` | `AuthorizationController`, `AuthorizationHandler` | Register plug authz |
| `noether.ledger.tests.factories` | `UserFactory`, `LedgerFactory`, `UnitFactory`, `AccountFactory`, `TransactionFactory` (+`posted_transaction` helper) | Plug test fixtures |

## Posting service signatures (stable contract)

```python
def create_transaction(
    *,
    ledger: Ledger,
    description: str,
    occurred_at: datetime,
    entries: list[EntryInput],  # EntryInput(account, direction, amount, metadata=None)
    metadata: dict | None = None,
    created_by: User,
) -> Transaction: ...  # returns DRAFT


def post_transaction(*, transaction: Transaction, posted_by: User) -> Transaction:
    """Atomic. Runs kernel invariants then domain validators.
    Raises ConservationError / DomainValidationError / ImmutabilityError."""


def reverse_transaction(
    *,
    transaction: Transaction,
    reversed_by: User,
    description: str | None = None,
    occurred_at: datetime | None = None,
) -> Transaction: ...  # returns the posted mirror transaction
```

## Slugged plug models (ADR-0014)

Inherit `SluggedModel`, declare the uniqueness scope, and add the matching
constraint. An empty scope means globally unique.

```python
from noether.ledger.models_base import SluggedModel


class Meter(SluggedModel, NoetherBaseModel):
    SLUG_SCOPE_FIELDS = ("ledger",)
    ledger = models.ForeignKey("ledger.Ledger", on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["ledger", "slug"], name="unique_meter_slug"),
        ]
```

Use `SlugStr` for the spec field. Nothing else is needed: any viewset deriving
from `NoetherBaseViewSet` will address the model by slug or UUID automatically,
scoped by its own `get_queryset()`.

## Identifier fields in plug specs (ADR-0016)

Type every UUID identifier field as `ExternalId`, never `pydantic.UUID4`:

```python
from noether.resources.base import ExternalId, NoetherResource


class MeterSpec(NoetherResource):
    id: ExternalId | None = None
    ledger: ExternalId
```

`UUID4` asserts the version bit, so it rejects the UUIDv7 identifiers the core
now generates. `ExternalId` accepts any UUID version, which is required because
v4 rows created before ADR-0016 and v7 rows created after it coexist in the same
column permanently.

Plug viewsets deriving from `NoetherCreateMixin` inherit client-supplied IDs and
their replay/conflict semantics for free — no per-plug work, provided the spec's
`id` field is optional as above.

## Taggable plug models (ADR-0013)

Inherit `TaggableMixin` to get the denormalized `tags` ArrayField, declare the
resource type, and mount the viewset actions:

```python
from noether.tagging.models import TaggableMixin
from noether.api.viewsets.tags import TagMixin
from noether.tagging.filters import TagFilter


class Meter(TaggableMixin, NoetherBaseModel):
    ledger = models.ForeignKey("ledger.Ledger", on_delete=models.CASCADE)


class MeterViewSet(TagMixin, LedgerScopedMixin, NoetherModelViewSet):
    tag_resource_type = "meter"  # matches TagConfig.resource

    def authorize_tag(self, instance):
        self.check_ledger_permission("tag__apply")


class MeterFilters(filters.FilterSet):
    tags = TagFilter()
```

Tag configs themselves are created against the ledger via
`/api/v1/ledgers/{id}/tag-configs/` with `resource="meter"`. See
`docs/concepts/05-tags.md`.

## Guarantees to plugs

1. These signatures and exception types are semver-stable (break only on
   core major).
2. `post_transaction` calls each registered `TransactionValidator` of the
   ledger's domain, in registration order, with
   `(transaction, entries, balances_after)`. `balances_after` maps
   `account_id → Decimal` **normalized by the account type's normal side**
   (ADR-0010): a correctly-typed account in its natural state is positive,
   so sign-policy validators are simply `normalized >= 0` checks.
3. Kernel invariants (docs/concepts/01) always run BEFORE domain validators.
4. All service functions are safe to call from Celery tasks and viewsets
   alike; they manage their own DB transactions.

## Plug URL mounting (ADR-0011)

Declare a urlconf module on the config; core mounts it — plugs never touch
the root urlconf:

```python
DomainConfig(
    slug="energy",
    ...,
    urls="noether_energy.api.urls",  # module exposing `urlpatterns`
)
```

Core includes it at `api/v1/plugs/<slug>/`, resolved lazily after all apps
are loaded.

## Ledger creation service (ADR-0011)

```python
from noether.domains.services import create_ledger

ledger = create_ledger(
    domain_slug="energy",
    name="Home Microgrid",
    owner=user,  # granted the Owner role
    chart_template="household",  # optional; instantiates units + accounts
)
```

Identical semantics to `POST /api/v1/ledgers/` (the viewset delegates to
this service). Raises `DomainConfigError` for unknown domains/templates.
