# ADR-0009: Resource-package structure and django-filter for list filtering

- Status: Accepted
- Date: 2026-08-28
- Deciders: rithviknishad

## Context

Two structural gaps existed in the initial layout:

1. Pydantic specs were defined inline inside `noether/ledger/api/*.py` viewset
   modules instead of per-resource packages (with constants/enums in sibling
   modules).
2. List filtering was hand-parsed from `request.query_params` inside
   `get_queryset` instead of using django-filter `FilterSet` classes with
   `filterset_class` + `DjangoFilterBackend`.

## Decision

- Specs live in `noether/ledger/resources/<resource>/spec.py` — one package per
  resource (ledger, account, unit, transaction, member, price, role, domain).
  Enum/choice re-exports live in sibling `constants.py` modules (e.g.
  `transaction/constants.py`). Viewset modules keep only viewsets, FilterSets,
  and authorization glue.
- `noether/resources/base.py` remains the canonical home of `NoetherResource`
  (public API contract, used by plugs); ledger resource packages import from it.
- List filtering uses django-filter `FilterSet` classes declared in the viewset
  module, with `DjangoFilterBackend`. Public query param names are unchanged.
  Computation params (`as_of`, `value_in` on balance) stay hand-parsed — they
  are not queryset filters.

## Consequences

- Structure is predictable and consistent; plugs follow the same layout.
- Invalid UUID/datetime filter values now return 400 via FilterSet validation
  (previously ad-hoc); invalid booleans are ignored (django-filter behavior).
- django-filter is a new runtime dependency (`django_filters` in INSTALLED_APPS).
