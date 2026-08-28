# ADR-0008: Stack and tooling

- Status: Accepted
- Date: 2026-08-27
- Deciders: Rithvik Nishad

## Context

Mirror Care's proven stack where it earns its keep; modernize where Care
carries legacy (pipenv).

## Decision

| Concern | Choice |
| --- | --- |
| Language | Python 3.13 (strict) |
| Framework | Django 5.2 LTS + Django REST Framework |
| Serialization/validation | pydantic v2 specs (`NoetherResource`) over DRF serializers, Care's pattern |
| API docs | drf-spectacular (OpenAPI) |
| Auth | JWT via djangorestframework-simplejwt |
| Routing | drf-nested-routers (`/ledgers/{id}/…`) |
| DB | PostgreSQL 16 (jsonb, CTEs); psycopg 3 |
| Cache/broker | Redis |
| Async | Celery + celery-beat (snapshots, verifier, valuation fetchers) |
| Packages | **uv** (`pyproject.toml` + `uv.lock`) |
| Lint/format | Ruff (line length & rule set in `pyproject.toml`) |
| Tests | Django test runner + factory-boy + hypothesis + coverage.py |
| Config | django-environ; 12-factor env vars; settings split base/local/test/deployment |
| Containers | Docker Compose (db, redis, backend, celery, beat) + Makefile |
| CI | GitHub Actions: ruff, migrations-check, test w/ fail_under=100 |

Naming: Django project package `noether`, core apps `noether.ledger`,
`noether.security`, `noether.users`, `noether.domains`; config package
`config` (Care parity).

## Consequences

- (+) Anyone fluent in Care is fluent here; agents can crib Care patterns.
- (+) uv gives fast, reproducible, PEP-621-native installs.
- (n) Django 5.2 LTS chosen over 6.0 for library compatibility maturity;
  revisit at 6.x LTS.

## Alternatives considered

- FastAPI (user's usual backend preference): rejected for this project —
  the Care patterns being reused (EMRBaseViewSet, plug manager, RBAC
  controllers, migrations discipline) are Django-native, and Django's ORM
  transaction/locking semantics are load-bearing for the kernel.
- pipenv (Care parity): rejected — slower, fading ecosystem.
