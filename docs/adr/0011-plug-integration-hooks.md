# ADR-0011: First-Class Plug Integration Hooks

- Status: Accepted
- Date: 2026-08-28
- Deciders: Rithvik Nishad

## Context

Building noether-finance and noether-energy against the public API surfaced
four contract gaps (all worked around in the plugs):

1. No URL-mounting hook — energy appended to the ROOT_URLCONF's
   `urlpatterns` from `AppConfig.ready()`, an undocumented and fragile hack.
2. `instantiate_chart` / ledger creation wasn't public — plugs needing a
   ledger programmatically had to round-trip through their own REST API.
3. `DomainRegistry.register` raised on ANY re-registration, so both plugs
   guarded with try/except around `ready()` (which Django may run more than
   once in tests/autoreload).
4. `LedgerScopedMixin` (ledger resolution + permission check for nested
   routes) wasn't exported; energy re-implemented it.

## Decision

1. **Plug URLs**: `DomainConfig` grows `urls: str | None` — a dotted path to
   a plug urlconf module (e.g. `"noether_energy.api.urls"`). Core's
   `config/urls.py` mounts every registered domain's urlconf at
   `api/v1/plugs/<slug>/` via a dynamic include resolved after plug apps are
   ready. Plugs MUST NOT touch the root urlconf.
2. **Ledger creation service**: `noether.domains.services` exports
   `create_ledger(*, domain_slug, name, owner, chart_template=None) -> Ledger`
   — creates the ledger row, instantiates default units + the chart template,
   and assigns the owner role, identically to the REST path (which now
   delegates to it). `instantiate_chart` becomes public alongside it.
3. **Idempotent registration**: `DomainRegistry.register` is a no-op when the
   incoming config is `==` to the one already registered for that slug
   (frozen dataclass equality on slug/name/version/types/units/templates and
   identity classes of validators/valuation); it still raises
   `DomainConfigError` on a *conflicting* re-registration.
4. **Exported mixin**: `noether.api.viewsets.base` exports
   `LedgerScopedMixin` (`get_ledger()`, `check_ledger_permission(slug)`), and
   it joins the public API table.

## Consequences

- Plugs contain zero core-workaround code; `ready()` shrinks to
  registration calls.
- The REST and service ledger-creation paths cannot drift (single
  implementation).
- Re-running `ready()` is safe by contract, matching Django's actual
  lifecycle.
- Core takes on urlconf-mounting responsibility and its ordering
  constraints (plug urls resolve lazily at first request, after all apps
  are loaded).

## Alternatives considered

- Entry-points-based URL discovery (setuptools): heavier, less explicit than
  declaring in the already-central `DomainConfig`. Rejected.
- Making `register` always-overwrite: hides genuine double-registration bugs
  (e.g. two plugs claiming one slug). Rejected in favour of
  identical-tolerant/conflict-raising.
