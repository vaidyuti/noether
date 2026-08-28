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
| `noether.ledger.services.posting` | `create_transaction(...)`, `post_transaction(...)`, `reverse_transaction(...)` | THE only write path to the ledger |
| `noether.ledger.services.balances` | `get_balance(account, as_of=None)` (normalized), `get_raw_balance(account, as_of=None)`, `get_market_value(account, value_in, as_of=None)` | Read helpers |
| `noether.resources.base` | `NoetherResource` | pydantic spec base for plug APIs |
| `noether.api.viewsets.base` | `NoetherBaseViewSet`, `NoetherModelViewSet`, `NoetherModelReadOnlyViewSet`, `LedgerScopedMixin` | Plug viewsets |
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
