import datetime
from decimal import Decimal

from pydantic import UUID4, BaseModel, field_validator

from noether.ledger.models import Transaction
from noether.ledger.resources.transaction.constants import EntryDirection
from noether.resources.base import NoetherResource


class EntrySpec(BaseModel):
    account: UUID4
    direction: EntryDirection
    amount: Decimal
    metadata: dict = {}

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, value):
        if isinstance(value, float):
            value = str(value)
        return value


class TransactionCreateSpec(BaseModel):
    description: str = ""
    occurred_at: datetime.datetime
    entries: list[EntrySpec]
    metadata: dict = {}
    post: bool = False


class TransactionUpdateSpec(NoetherResource):
    __model__ = Transaction
    description: str | None = None
    occurred_at: datetime.datetime | None = None
    metadata: dict | None = None


class ReverseSpec(BaseModel):
    description: str | None = None
    occurred_at: datetime.datetime | None = None


class TransactionReadSpec(NoetherResource):
    __model__ = Transaction
    id: UUID4 | None = None
    status: str = ""
    description: str = ""
    occurred_at: datetime.datetime | None = None
    posted_at: datetime.datetime | None = None
    reverses: UUID4 | None = None
    reversed_by: UUID4 | None = None
    metadata: dict = {}
    entries: list[dict] = []
    created_date: datetime.datetime | None = None

    @classmethod
    def perform_extra_serialization(cls, mapping, obj):
        super().perform_extra_serialization(mapping, obj)
        mapping["reverses"] = obj.reverses.external_id if obj.reverses_id else None
        mapping["reversed_by"] = obj.reversed_by.external_id if obj.reversed_by_id else None
        mapping["entries"] = [
            {
                "id": str(entry.external_id),
                "account": str(entry.account.external_id),
                "direction": entry.direction,
                "amount": str(entry.amount),
                "metadata": entry.metadata,
            }
            for entry in obj.entries.select_related("account").order_by("id")
        ]
