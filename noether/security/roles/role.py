from dataclasses import dataclass, field

from noether.security.permissions.base import (
    AccountPermissions,
    BalancePermissions,
    PermissionController,
    PricePermissions,
    TagPermissions,
    TransactionPermissions,
    UnitPermissions,
)


@dataclass(frozen=True)
class Role:
    name: str
    description: str
    permissions: tuple[str, ...] = field(default_factory=tuple)


ALL_PERMISSIONS = tuple(
    permission.name
    for handler in PermissionController.internal_permission_handlers
    for permission in handler
)

READ_PERMISSIONS = tuple(p for p in ALL_PERMISSIONS if p.endswith("__read"))

OWNER_ROLE = Role(
    name="Owner",
    description="Full control including membership and ledger settings",
    permissions=ALL_PERMISSIONS,
)

BOOKKEEPER_ROLE = Role(
    name="Bookkeeper",
    description="Day-to-day recording",
    permissions=(
        *READ_PERMISSIONS,
        AccountPermissions.account__write.name,
        AccountPermissions.account__archive.name,
        UnitPermissions.unit__write.name,
        TransactionPermissions.transaction__create.name,
        TransactionPermissions.transaction__write.name,
        TransactionPermissions.transaction__post.name,
        TransactionPermissions.transaction__reverse.name,
        TransactionPermissions.transaction__delete.name,
        PricePermissions.price__write.name,
        TagPermissions.tag__write.name,
        TagPermissions.tag__apply.name,
    ),
)

AUDITOR_ROLE = Role(
    name="Auditor",
    description="Read everything, change nothing",
    permissions=READ_PERMISSIONS,
)

VIEWER_ROLE = Role(
    name="Viewer",
    description="Balances and account tree only",
    permissions=(
        AccountPermissions.account__read.name,
        BalancePermissions.balance__read.name,
    ),
)


class RoleController:
    override_roles: list[Role] = []

    internal_roles: list[Role] = [OWNER_ROLE, BOOKKEEPER_ROLE, AUDITOR_ROLE, VIEWER_ROLE]

    @classmethod
    def get_roles(cls) -> list[Role]:
        return cls.internal_roles + cls.override_roles

    @classmethod
    def register_role(cls, role: Role) -> None:
        if role not in cls.override_roles:
            cls.override_roles.append(role)

    @classmethod
    def get_role_by_name(cls, name: str) -> Role | None:
        for role in cls.get_roles():
            if role.name == name:
                return role
        return None
