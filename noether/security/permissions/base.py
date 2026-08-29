import enum
from dataclasses import dataclass


@dataclass
class PermissionMeta:
    name: str
    description: str = ""


class LedgerPermissions(enum.Enum):
    ledger__read = PermissionMeta("Read ledger")
    ledger__write = PermissionMeta("Update ledger")
    ledger__delete = PermissionMeta("Delete ledger")
    ledger__manage_members = PermissionMeta("Manage ledger members")


class AccountPermissions(enum.Enum):
    account__read = PermissionMeta("Read accounts")
    account__write = PermissionMeta("Create/update accounts")
    account__archive = PermissionMeta("Archive accounts")


class UnitPermissions(enum.Enum):
    unit__read = PermissionMeta("Read units")
    unit__write = PermissionMeta("Create/update units")


class TransactionPermissions(enum.Enum):
    transaction__read = PermissionMeta("Read transactions/entries")
    transaction__create = PermissionMeta("Create draft transactions")
    transaction__write = PermissionMeta("Update draft transactions")
    transaction__post = PermissionMeta("Post transactions")
    transaction__reverse = PermissionMeta("Reverse transactions")
    transaction__delete = PermissionMeta("Delete draft transactions")


class BalancePermissions(enum.Enum):
    balance__read = PermissionMeta("Read balances")


class PricePermissions(enum.Enum):
    price__read = PermissionMeta("Read prices")
    price__write = PermissionMeta("Write prices")


class TagPermissions(enum.Enum):
    tag__read = PermissionMeta("Read tag configs")
    tag__write = PermissionMeta("Create/update tag configs")
    tag__apply = PermissionMeta("Apply/remove tags on taggable resources")


class PermissionHandler:
    pass


class PermissionController:
    """All permissions used within noether; plugs may register more."""

    override_permission_handlers: list = []

    internal_permission_handlers = [
        LedgerPermissions,
        AccountPermissions,
        UnitPermissions,
        TransactionPermissions,
        BalancePermissions,
        PricePermissions,
        TagPermissions,
    ]

    cache = {}

    @classmethod
    def build_cache(cls):
        cache = {}
        handlers = cls.internal_permission_handlers + cls.override_permission_handlers
        for handler in handlers:
            for permission in handler:
                cache[permission.name] = permission.value
        cls.cache = cache

    @classmethod
    def has_permission(cls, slug: str) -> bool:
        if not cls.cache:
            cls.build_cache()
        return slug in cls.cache

    @classmethod
    def get_permissions(cls) -> dict:
        if not cls.cache:
            cls.build_cache()
        return cls.cache

    @classmethod
    def register_permission_handler(cls, handler) -> None:
        if handler not in cls.override_permission_handlers:
            cls.override_permission_handlers.append(handler)
        cls.cache = {}
