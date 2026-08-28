# 12-Factor & Deployment

## Factor mapping

| Factor | Implementation |
| --- | --- |
| I. Codebase | One repo per deployable: core + one per plug |
| II. Dependencies | uv, `pyproject.toml` + `uv.lock`; no system deps assumed |
| III. Config | env vars only (django-environ); `.env.example` documents every var; `.env` gitignored |
| IV. Backing services | DATABASE_URL, REDIS_URL — attachable resources |
| V. Build/release/run | Docker image build → env-injected release → run |
| VI. Processes | Stateless web/worker/beat; no local disk state |
| VII. Port binding | gunicorn binds $PORT |
| VIII. Concurrency | scale web/worker containers independently |
| IX. Disposability | fast boot; Celery acks_late + idempotent tasks |
| X. Dev/prod parity | docker compose mirrors prod topology; same Postgres/Redis versions |
| XI. Logs | stdout, JSON in deployment settings |
| XII. Admin | `manage.py` one-offs (`migrate`, `sync_permissions_roles`, `sync_domains`) |

## Environment variables (core)

```
DJANGO_SETTINGS_MODULE=config.settings.deployment
DJANGO_SECRET_KEY=…
DATABASE_URL=postgres://…
REDIS_URL=redis://…
NOETHER_PLUGS=noether_finance,noether_energy
ALLOWED_HOSTS=…
CORS_ALLOWED_ORIGINS=…
SNAPSHOT_CRON="0 2 * * *"           # balance snapshots
INTEGRITY_VERIFY_CRON="30 2 * * *"  # conservation auditor
INTEGRITY_ALERT_WEBHOOK=…           # optional
```

## Process topology

```
web     gunicorn config.wsgi
worker  celery -A config.celery_app worker
beat    celery -A config.celery_app beat
```

## Celery task inventory (core)

| Task | Trigger | Purpose |
| --- | --- | --- |
| `ledger.snapshot_balances` | beat (SNAPSHOT_CRON) | Write BalanceSnapshot rows |
| `ledger.verify_integrity` | beat (INTEGRITY_VERIFY_CRON) | Re-derive balances, check conservation, alert on drift |
| `domains.fetch_prices` | beat, per ValuationStrategy schedule | Run plug price fetchers → UnitPrice |

All tasks idempotent; verifier and snapshotter take advisory locks to
prevent overlap.
