import datetime
from decimal import Decimal

from pydantic import UUID4, field_validator

from noether.ledger.models import UnitPrice
from noether.resources.base import NoetherResource


class UnitPriceSpec(NoetherResource):
    __model__ = UnitPrice
    unit: str
    quote_unit: str
    price: Decimal
    as_of: datetime.datetime
    source: str = ""
    metadata: dict = {}

    @field_validator("price", mode="before")
    @classmethod
    def coerce_price(cls, value):
        if isinstance(value, float):
            value = str(value)
        return value

    def perform_extra_deserialization(self, is_update, obj):
        obj.unit = self._unit_row
        obj.quote_unit = self._quote_unit_row


class UnitPriceReadSpec(NoetherResource):
    __model__ = UnitPrice
    id: UUID4 | None = None
    unit: str | None = None
    quote_unit: str | None = None
    price: str | None = None
    as_of: datetime.datetime | None = None
    source: str = ""
    metadata: dict = {}

    @classmethod
    def perform_extra_serialization(cls, mapping, obj):
        super().perform_extra_serialization(mapping, obj)
        mapping["unit"] = obj.unit.symbol
        mapping["quote_unit"] = obj.quote_unit.symbol
        mapping["price"] = str(Decimal(obj.price).quantize(Decimal("1.0000000000")))
