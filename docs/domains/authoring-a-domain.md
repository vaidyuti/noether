# Authoring a Domain Plug

This document is the **binding contract** between noether-core and domain
plugs (`noether-finance`, `noether-energy`, …). A plug that follows this
document can be developed in a separate repo, in parallel, with no access
to core internals beyond the interfaces named here.

## What a plug is

A pip-installable Python package containing one Django app. Example layout
(`noether-finance` repo):

```
noether-finance/
├── pyproject.toml               # name = "noether-finance", deps: noether-core
├── docs/                        # plug's own docs/ (same golden rules)
├── noether_finance/
│   ├── __init__.py
│   ├── apps.py                  # AppConfig with ready() registrations
│   ├── domain.py                # DomainConfig definition
│   ├── validators.py            # TransactionValidator implementations
│   ├── valuation.py             # ValuationStrategy (optional)
│   ├── charts.py                # ChartTemplate(s)
│   ├── security/
│   │   ├── permissions.py       # enum handlers (optional)
│   │   └── roles.py             # extra Role definitions (optional)
│   ├── models/                  # plug-owned tables (optional), FK to core
│   ├── resources/               # pydantic specs for plug APIs (optional)
│   │   └── <resource>/          # one package per resource
│   │       ├── spec.py          # CreateSpec/UpdateSpec/ReadSpec extending NoetherResource
│   │       └── constants.py     # enums/choices for the resource (optional)
│   ├── api/                     # extra viewsets (optional): viewsets + FilterSets + authz only
│   ├── tasks/                   # celery tasks (optional)
│   ├── migrations/
│   └── tests/                   # 100% coverage, same standard as core
└── Makefile
```

## Activation (12-factor)

Deployments list plugs in the environment:

```
NOETHER_PLUGS=noether_finance,noether_energy
```

Core's `plug_config.py` (`PlugManager`) reads this, appends each
plug's app to `INSTALLED_APPS`, and merges plug settings. A plug MUST NOT
require manual `settings.py` edits. Plug-specific config uses env vars
prefixed with the plug slug, e.g. `NOETHER_FINANCE_PRICE_PROVIDER=…`.

## Registration hooks

All registration happens in `AppConfig.ready()`:

```python
from django.apps import AppConfig


class NoetherFinanceConfig(AppConfig):
    name = "noether_finance"

    def ready(self):
        from noether.domains.registry import DomainRegistry
        from noether.security.permissions.base import PermissionController
        from noether.security.roles.role import RoleController
        from noether.security.authorization.base import AuthorizationController

        from .domain import FINANCE_DOMAIN

        DomainRegistry.register(FINANCE_DOMAIN)
        # optional:
        # PermissionController.register_permission_handler(FinancePermissions)
        # RoleController.register_role(ACCOUNTANT_ROLE)
        # AuthorizationController.register_override_controller(FinanceAuthz)
```

## The DomainConfig contract

```python
from noether.domains.config import (
    DomainConfig, AccountTypeDef, UnitDef, ChartTemplate, ChartNode,
)

FINANCE_DOMAIN = DomainConfig(
    slug="finance",                    # unique, [a-z0-9-], ≤ 32 chars
    name="Personal Finance",
    version="1.0.0",                   # plug's own semver
    account_types=[
        # name: unique within domain; normal_balance: "debit" | "credit"
        AccountTypeDef(name="asset",     normal_balance="debit"),
        AccountTypeDef(name="liability", normal_balance="credit"),
        AccountTypeDef(name="equity",    normal_balance="credit"),
        AccountTypeDef(name="income",    normal_balance="credit"),
        AccountTypeDef(name="expense",   normal_balance="debit"),
        AccountTypeDef(name="trading",   normal_balance="debit"),
    ],
    default_units=[
        UnitDef(symbol="INR", name="Indian Rupee", precision=2),
    ],
    chart_templates=[…],               # see below
    validators=[…],                    # see below
    valuation=…,                       # optional ValuationStrategy
)
```

`DomainRegistry.register()` validates the config (unique slug, valid
account types, etc.) at startup — a bad config fails boot, not runtime.
`manage.py sync_domains` mirrors registered configs into the `Domain` table.

### AccountTypeDef

`normal_balance` drives balance normalization (ADR-0010): every read/hook
surface reports `raw × (+1 if debit-normal else −1)`, so choose sides such
that an account's natural state is its normal side (what it *holds* or
*accumulates* debit-normal only if debits grow it). The kernel's stored fold
stays raw debits−credits.

### ChartTemplate

A named starter account tree instantiated when a ledger is created with
`chart_template=<name>`:

```python
ChartTemplate(
    name="default",
    nodes=[
        ChartNode(path="Assets", account_type="asset", unit="INR", placeholder=True),
        ChartNode(path="Assets/Bank", account_type="asset", unit="INR"),
        ChartNode(path="Expenses", account_type="expense", unit="INR", placeholder=True),
        ChartNode(path="Expenses/Food", account_type="expense", unit="INR"),
        ChartNode(path="Income/Salary", account_type="income", unit="INR"),
        ChartNode(path="Trading/INR", account_type="trading", unit="INR"),
    ],
)
```

Paths are `/`-separated; intermediate nodes are auto-created as
placeholders; `unit` references a symbol from `default_units` (all
referenced units are created in the new ledger).

### TransactionValidator

Domain hooks run at **post time**, inside the posting DB transaction, after
kernel invariants pass. Raise `noether.ledger.exceptions.DomainValidationError`
to reject the post (maps to HTTP 400 with your message).

```python
from noether.domains.validators import TransactionValidator


class NonNegativeBalances(TransactionValidator):
    """Energy storage cannot go below zero."""

    def validate(self, transaction, entries, balances_after) -> None:
        # transaction: kernel Transaction (posted-pending)
        # entries: list[Entry] being posted
        # balances_after: {account_id: Decimal} post-application balances
        #                 for affected accounts, NORMALIZED by each account
        #                 type's normal side (ADR-0010) — natural state is
        #                 positive. Computed by core, already locked —
        #                 validators MUST NOT query balances themselves or
        #                 perform writes.
        for entry in entries:
            if entry.account.metadata.get("non_negative") and balances_after[entry.account_id] < 0:
                raise DomainValidationError(f"{entry.account.name} cannot go negative")
```

Rules for validators:
- MUST be side-effect free (no writes, no network).
- MUST be deterministic.
- Run in registration order; first failure aborts the post.

### ValuationStrategy (optional)

```python
from noether.domains.valuation import ValuationStrategy


class MarketDataFetcher(ValuationStrategy):
    schedule = "0 18 * * 1-5"  # crontab, celery-beat entry auto-registered

    def fetch_prices(self, ledger) -> list[PriceQuote]:
        """Return PriceQuote(unit_symbol, quote_unit_symbol, price, as_of, source).
        Core persists them as UnitPrice rows. Network allowed here."""
```

Read-side valuation (`?value_in=`) is served by core from `UnitPrice` data;
strategies only supply data.

## What plugs MUST NOT do

1. Import from any core module not listed in `docs/domains/public-api.md`.
2. Add fields, migrations, or signals to core models. Plug data lives in
   plug tables (FK to core via `to_field="external_id"` or plain FK) or in
   core `metadata`/`settings` jsonb under the `"<slug>": {…}` namespace.
3. Mutate posted transactions or balances through any path other than the
   kernel posting service.
4. Register anything outside `AppConfig.ready()`.
5. Ship with < 100% branch coverage (same ADR-0003 standard; plug CI must
   run coverage with `fail_under = 100`).

## Plug testing requirements

- Install core as a dependency; run against core's test settings
  (`config.settings.test` with the plug in `NOETHER_PLUGS`).
- Must include: DomainConfig registration test, chart instantiation test,
  every validator branch (MC/DC policy), valuation strategy tests with
  mocked network, API tests for any plug endpoints.
- Core publishes reusable test factories under `noether.ledger.tests.factories`
  (users, ledgers, accounts, transactions) — use them, don't fork them.

## Versioning & compatibility

- Core follows semver; the plug contract (this doc + `public-api.md`) only
  breaks on core major versions.
- Plugs pin `noether-core>=X.Y,<X+1`.
