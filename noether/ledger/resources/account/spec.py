import datetime

from pydantic import UUID4

from noether.ledger.models import Account
from noether.resources.base import NoetherResource


class AccountSpec(NoetherResource):
    __model__ = Account
    name: str
    account_type: str
    unit: UUID4
    parent: UUID4 | None = None
    is_placeholder: bool = False
    metadata: dict = {}

    def perform_extra_deserialization(self, is_update, obj):
        obj.unit = self._unit_row
        obj.parent = self._parent_row


class AccountUpdateSpec(NoetherResource):
    __model__ = Account
    name: str | None = None
    metadata: dict | None = None


class AccountReadSpec(NoetherResource):
    __model__ = Account
    id: UUID4 | None = None
    name: str = ""
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
