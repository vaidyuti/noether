import datetime

from pydantic import UUID4

from noether.extensions.base import ExtensionResource
from noether.extensions.validator import (
    ExtensionListRenderer,
    ExtensionRetrieveRenderer,
    ExtensionValidator,
)
from noether.ledger.models import Account
from noether.resources.base import NoetherResource, SlugStr


class AccountSpec(ExtensionValidator, NoetherResource):
    __model__ = Account
    __extension_resource__ = ExtensionResource.account
    name: str
    slug: SlugStr | None = None
    account_type: str
    unit: UUID4
    parent: UUID4 | None = None
    is_placeholder: bool = False
    metadata: dict = {}

    def perform_extra_deserialization(self, is_update, obj):
        obj.unit = self._unit_row
        obj.parent = self._parent_row


class AccountUpdateSpec(ExtensionValidator, NoetherResource):
    __model__ = Account
    __extension_resource__ = ExtensionResource.account
    name: str | None = None
    slug: SlugStr | None = None
    metadata: dict | None = None


class AccountReadSpec(ExtensionListRenderer, NoetherResource):
    __model__ = Account
    __extension_resource__ = ExtensionResource.account
    id: UUID4 | None = None
    name: str = ""
    slug: str | None = None
    account_type: str = ""
    unit: str | None = None
    parent: UUID4 | None = None
    is_placeholder: bool = False
    archived: bool = False
    metadata: dict = {}
    created_date: datetime.datetime | None = None

    @classmethod
    def perform_extra_serialization(cls, mapping, obj):
        super().perform_extra_serialization(mapping, obj)
        mapping["unit"] = obj.unit.symbol
        mapping["parent"] = obj.parent.external_id if obj.parent_id else None


class AccountRetrieveSpec(ExtensionRetrieveRenderer, AccountReadSpec):
    pass
