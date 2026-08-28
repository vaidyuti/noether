# Security: RBAC Model

Pattern lifted from Care's `security` app (PermissionController /
RoleController / AuthorizationController), simplified to a single context:
**the Ledger** (ADR-0004).

## Model

```
Permission        — synced from code enums to DB (sync_permissions_roles cmd)
Role              — named bundle of permissions; built-in (code-defined) or
                    custom (ledger-scoped, future)
RolePermission    — role ↔ permission
LedgerUser        — (ledger, user, role) membership; unique (ledger, user)
```

A user's capabilities in a ledger = the permissions of their role in that
ledger. Superusers bypass (consistent with Care). Users with no membership
have no access — there is no public ledger concept in v1.

## Built-in roles

| Role | Description | Permissions (summary) |
| --- | --- | --- |
| **Owner** | Full control incl. membership & ledger settings | everything |
| **Bookkeeper** | Day-to-day recording | account read/write, transaction create/post/reverse, unit read/write, price write, read everything |
| **Auditor** | Read-everything, change-nothing | all `*__read` |
| **Viewer** | Balances & account tree only | account read, balance read (NOT entry/transaction read) |

Plugs may register additional roles via `RoleController.override_roles`
(e.g. noether-energy's `MeterAgent`: a service identity allowed only
`transaction__create` + `transaction__post`).

## Permission naming

`<resource>__<action>` slugs, defined as Python enums per resource, e.g.:

```
ledger__read, ledger__write, ledger__delete, ledger__manage_members
account__read, account__write, account__archive
unit__read, unit__write
transaction__read, transaction__create, transaction__write   (drafts)
transaction__post, transaction__reverse, transaction__delete (drafts only)
balance__read
price__read, price__write
```

## Enforcement flow (per request)

1. Viewset resolves the ledger from the nested route
   (`/ledgers/{ledger_id}/…`).
2. `authorize_<action>()` on the viewset calls
   `AuthorizationController.call("can_<action>_<resource>", user, ledger, obj)`.
3. Handlers check `LedgerUser` membership → role → permission slugs.
4. Querysets are always pre-filtered to ledgers the user belongs to
   (`get_accessible_ledgers(user)`) — object-level 404, not 403 leak.

Controllers keep Care's plug-override chain: plugs can register override
authz handlers that run before internal ones.
