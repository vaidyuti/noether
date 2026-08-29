# CLAUDE.md

Guidance for AI coding agents working in this repository. Read this file in full
before making any change.

## What is noether?

noether is a **domain-agnostic double-entry conservation ledger**. The core knows
nothing about money, energy, or water — it knows only *quantities that must
balance*. Domain meaning arrives exclusively through **plugs** (separate repos,
e.g. `noether-finance`, `noether-energy`).

Stack: Python 3.13, Django 5.2 LTS, DRF, pydantic v2, PostgreSQL, Redis, Celery,
managed with **uv**.

## Golden rules (non-negotiable)

1. **The core stays domain-agnostic.** If a concept only makes sense for money,
   energy, or any single domain, it belongs in a plug — not in `noether/`. No
   domain vocabulary (`revenue`, `generation`, `kWh`) in core code, tests, or
   docs.
2. **Test-driven development, 100% branch coverage, from day 0.** Write the test
   first. `make test` runs `coverage --fail-under=100` and must exit 0. Nothing
   merges below 100%.
3. **`# pragma: no cover` is banned** unless the exemption is listed in
   `docs/operations/coverage-exceptions.md` with a justification.
4. **Docs are part of the change.** Behaviour changes update `docs/`. Decisions
   get an ADR in `docs/adr/`. ADRs are immutable once Accepted — supersede,
   never edit.
5. **Posted transactions are immutable.** Corrections happen through reversal
   transactions only. See `docs/adr/0001`.
6. **No floats, ever.** Quantities are `Decimal` (`max_digits=30`,
   `decimal_places=10`), serialized as JSON strings.
7. **The plug contract is frozen.** `docs/domains/public-api.md` is the ONLY
   surface plugs may import. Adding to it is a deliberate act; breaking it is
   not allowed.
8. **12-factor.** All configuration comes from the environment. No secrets in
   code, no environment branching inside application logic.

## Before you write code

Read, in this order:

- `docs/README.md` — the docs index.
- `docs/concepts/01-ledger-kernel.md` — the six primitives and the numbered
  invariants. Everything else follows from these.
- The relevant ADR(s) in `docs/adr/`.
- The actual model, spec, viewset, and test files you are about to touch.

Never guess a function signature, model field, or API name. Search for the real
definition first.

## Architecture

```
noether/
├── ledger/          # the kernel: models, api, resources, services
│   ├── models/      # Domain, Ledger, Unit, Account, Transaction, Entry, balances
│   ├── resources/   # pydantic specs, one package per resource
│   ├── api/         # viewsets, FilterSets, authz glue only
│   └── services/    # posting, balances — the transactional core
├── resources/base.py    # NoetherResource: pydantic <-> model serialization
├── api/viewsets/base.py # NoetherBaseViewSet + lifecycle mixins
├── security/        # permissions, roles, authorization controllers
├── domains/         # domain registry (plugs register here)
└── users/
config/              # settings/{base,local,test,deployment}, api_router, celery_app
plugs/               # plug loading; activated via the NOETHER_PLUGS env var
docs/                # concepts, ADRs, domain authoring guide, api, operations
```

### Conventions

- **Specs live in `resources/<resource>/spec.py`**, one package per resource,
  with enums in a sibling `constants.py`. Viewset modules contain viewsets,
  FilterSets, and authorization glue — never spec definitions. See ADR-0009.
- **List filtering uses django-filter `FilterSet`s.** Never hand-parse
  `request.query_params` in `get_queryset`. (Computation parameters that are not
  queryset filters, like `as_of`, are the documented exception.)
- **Objects are addressed by `external_id` (UUID)**, never by primary key.
- **RBAC is flat and ledger-scoped.** A user holds a role in a ledger. Querysets
  are pre-filtered to accessible ledgers, so inaccessible objects return 404 —
  never leak existence with a 403.
- Errors: conservation violations → 400, immutability violations → 409.

## Commands

```bash
make test      # full suite + 100% coverage gate (must exit 0)
make lint      # ruff check + ruff format --check
make migrate
make run
uv run manage.py makemigrations --check   # must be clean before you commit
```

Run a subset while iterating:

```bash
uv run manage.py test tests.unit.test_posting --settings=config.settings.test
```

## Definition of done

A change is complete only when **all** of these hold:

- [ ] Tests were written first and cover every new branch.
- [ ] `make test` exits 0 at 100% coverage.
- [ ] `make lint` is clean.
- [ ] `makemigrations --check` is clean (migrations committed).
- [ ] Docs updated; an ADR added if a decision was made.
- [ ] `docs/domains/public-api.md` updated if the plug surface changed.
- [ ] The core is still domain-agnostic.

Do not report work as finished based on intent. Run the commands and paste the
real output.

## Git

- Conventional commit messages (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`).
- Commit signing may fail non-interactively; use
  `git -c commit.gpgsign=false commit` when it does.
- Never push, merge, rebase, or rewrite history unless explicitly asked.
