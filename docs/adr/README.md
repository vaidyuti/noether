# ADR Index

ADRs are numbered, immutable once **Accepted** (create a superseding ADR to
change a decision). Template: `template.md`.

| # | Title | Status |
| --- | --- | --- |
| [0001](0001-immutable-posted-transactions.md) | Immutable posted transactions; reversal-only corrections | Accepted |
| [0002](0002-valuation-as-overlay.md) | Valuation as computed overlay, not ledger entries | Accepted |
| [0003](0003-testing-standard.md) | 100% branch coverage + MC/DC-by-policy (DO-178B-inspired) | Accepted |
| [0004](0004-ledger-scoped-flat-rbac.md) | Ledger-scoped flat RBAC, no org hierarchy | Accepted |
| [0005](0005-plugin-architecture.md) | Domain plugins as separate repos; plug manager | Accepted |
| [0006](0006-amounts-and-units.md) | Decimal amounts, opaque per-ledger units, per-unit balancing | Accepted |
| [0007](0007-balance-materialization.md) | Materialized balances + snapshots + integrity verifier | Accepted |
| [0008](0008-stack-and-tooling.md) | Python 3.13 / Django / DRF+pydantic / uv / Postgres / Redis / Celery | Accepted |
| [0009](0009-resource-package-structure.md) | Specs in resources/ packages; django-filter for list filtering | Accepted |
| [0010](0010-normalized-balance-presentation.md) | Balances normalized by account-type normal side on all read/hook surfaces; raw stays internal | Accepted |
| [0011](0011-plug-integration-hooks.md) | First-class plug hooks: urls in DomainConfig, create_ledger service, idempotent registration, exported LedgerScopedMixin | Accepted |
