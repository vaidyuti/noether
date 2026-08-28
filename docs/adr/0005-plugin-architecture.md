# ADR-0005: Domain plugins as separate repos; plug manager

- Status: Accepted
- Date: 2026-08-27
- Deciders: Rithvik Nishad

## Context

The core must stay domain-agnostic (golden rule 3). The pattern: a `plugs`
package with a `PlugManager` that installs external Django apps from
configuration, and controllers with plug-override hooks.

## Decision

1. Each domain is a **separate repository / installable package**:
   `~/projects/noether-finance` (`noether_finance`),
   `~/projects/noether-energy` (`noether_energy`). Physically enforcing the
   boundary keeps the core honest.
2. Core ships the plug machinery: `plugs/` package (Plug, PlugManager) +
   `plug_config.py`. Plugs are declared via environment
   (12-factor): `NOETHER_PLUGS=noether_finance,noether_energy` for local
   path/pip installs.
3. A plug is a Django app whose `AppConfig.ready()` registers:
   - a `DomainConfig` into the **DomainRegistry**,
   - permission handlers into `PermissionController`,
   - roles into `RoleController`,
   - authz handlers into `AuthorizationController`,
   - Celery tasks (autodiscovered),
   - optional extra API routes under `/api/v1/plugs/<slug>/…`.
4. The full plug contract (interfaces, hook points, packaging, testing
   requirements) is specified in `docs/domains/authoring-a-domain.md` —
   that document is the contract subagents/parallel teams build against.
5. Plugs may add their own models/migrations in their own app namespace;
   they never migrate or monkey-patch core tables. Extension data goes in
   their own tables FK'd to core, or in core's `metadata`/`settings` jsonb
   fields under a `"<plug-slug>": {…}` namespace.

## Consequences

- (+) Core cannot grow domain warts; any number of domains develop in
  parallel against the documented contract.
- (−) Cross-repo development requires the contract docs to be kept precise;
  version compatibility handled by plugs pinning `noether-core`.
- (n) In CI, core tests run without plugs; plug CIs install core + itself.

## Alternatives considered

- In-repo `plugs/finance` extracted later: rejected — boundaries rot when
  not physically enforced.
- Setuptools entry-points discovery: viable, but env-var declaration is
  more 12-factor; may add entry-points sugar later.
