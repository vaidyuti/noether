# ADR-0004: Ledger-scoped flat RBAC, no org hierarchy

- Status: Accepted
- Date: 2026-08-27
- Deciders: Rithvik Nishad

## Context

Noether's initial use cases (personal finance, home energy) need multi-user
ledgers but no organizational nesting.

## Decision

1. The **Ledger is the sole authorization context**. Membership is
   `LedgerUser(ledger, user, role)`, unique per (ledger, user).
2. Roles are flat permission bundles. Built-ins: Owner, Bookkeeper,
   Auditor, Viewer (`docs/concepts/03-security-rbac.md`).
3. Controller pattern (PermissionController, RoleController,
   AuthorizationController with plug override chains) keeps the door open
   for plugs to add roles/permissions without core changes.
4. Permissions are code-defined enums synced to DB via
   `sync_permissions_roles` management command.
5. No organization layer in v1. If needed later, an Org model owning
   ledgers will be introduced by a superseding ADR; the controller
   pattern already accommodates additional contexts.

## Consequences

- (+) Authorization checks are one membership lookup; trivially cacheable.
- (+) Far smaller test matrix than hierarchical RBAC.
- (−) "Family of ledgers" administration requires per-ledger membership
  management for now.

## Alternatives considered

- Org hierarchy from day 0: rejected — YAGNI for the target use cases;
  enormous test surface.
- Django's built-in permissions: rejected — model-level, not object/ledger
  scoped; doesn't support plug-contributed roles cleanly.
