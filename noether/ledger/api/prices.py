import datetime
from decimal import Decimal

from pydantic import UUID4, field_validator
from rest_framework.exceptions import ValidationError

from noether.api.viewsets.base import (
    NoetherBaseViewSet,
    NoetherCreateMixin,
    NoetherListMixin,
    NoetherRetrieveMixin,
)
from noether.ledger.api.base import LedgerScopedMixin
from noether.ledger.models import Unit, UnitPrice
from noether.resources.base import NoetherResource
from noether.security.permissions.base import PricePermissions


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


class UnitPriceViewSet(
    LedgerScopedMixin,
    NoetherRetrieveMixin,
    NoetherCreateMixin,
    NoetherListMixin,
    NoetherBaseViewSet,
):
    database_model = UnitPrice
    pydantic_model = UnitPriceSpec
    pydantic_read_model = UnitPriceReadSpec

    def get_queryset(self):
        queryset = (
            UnitPrice.objects.filter(ledger=self.get_ledger(), deleted=False)
            .select_related("unit", "quote_unit")
            .order_by("-as_of")
        )
        params = self.request.query_params
        if params.get("unit"):
            queryset = queryset.filter(unit__symbol=params["unit"])
        if params.get("quote_unit"):
            queryset = queryset.filter(quote_unit__symbol=params["quote_unit"])
        if params.get("as_of_before"):
            queryset = queryset.filter(as_of__lt=params["as_of_before"])
        if params.get("as_of_after"):
            queryset = queryset.filter(as_of__gt=params["as_of_after"])
        return queryset

    def list(self, request, *args, **kwargs):
        self.check_ledger_permission(PricePermissions.price__read.name)
        return super().list(request, *args, **kwargs)

    def authorize_retrieve(self, model_instance):
        self.check_ledger_permission(PricePermissions.price__read.name)

    def authorize_create(self, instance):
        self.check_ledger_permission(PricePermissions.price__write.name)

    def validate_data(self, instance, model_obj=None):
        ledger = self.get_ledger()
        instance._unit_row = Unit.objects.filter(
            ledger=ledger, symbol=instance.unit, deleted=False
        ).first()
        if instance._unit_row is None:
            raise ValidationError(f"unknown unit {instance.unit!r}")
        instance._quote_unit_row = Unit.objects.filter(
            ledger=ledger, symbol=instance.quote_unit, deleted=False
        ).first()
        if instance._quote_unit_row is None:
            raise ValidationError(f"unknown unit {instance.quote_unit!r}")
        if instance.price <= 0:
            raise ValidationError("price must be > 0")

    def perform_create(self, instance):
        instance.ledger = self.get_ledger()
        super().perform_create(instance)
