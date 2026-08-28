# ADR-0009: Mirror Care's structural conventions (resources/ packages, django-filter)

- Status: Accepted
- Date: 2026-08-28
- Deciders: rithviknishad

## Context

noether-core deliberately borrows Care's (ohc.network/care) EMR architecture:
pydantic specs over DRF serializers, `EMRResource`-style base classes, plug
architecture. Two structural divergences remained:

1. Pydantic specs were defined inline inside `noether/ledger/api/*.py` viewset
   modules, while Care keeps them in per-resource packages under
   `care/emr/resources/<resource>/spec.py` (with constants/enums in sibling modules).
2. List filtering was hand-parsed from `request.query_params` inside
   `get_queryset`, while Care uses django-filter `FilterSet` classes with
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
  module (Care's convention), with `DjangoFilterBackend`. Public query param
  names are unchanged. Computation params (`as_of`, `value_in` on balance) stay
  hand-parsed — they are not queryset filters.

## Consequences

- Structure is predictable for anyone who knows Care; plugs follow the same layout.
- Invalid UUID/datetime filter values now return 400 via FilterSet validation
  (previously ad-hoc); invalid booleans are ignored (django-filter behavior).
- django-filter is a new runtime dependency (`django_filters` in INSTALLED_APPS).
