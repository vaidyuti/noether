from django_filters import rest_framework as filters
from rest_framework.exceptions import ValidationError

from noether.api.viewsets.base import (
    NoetherBaseViewSet,
    NoetherCreateMixin,
    NoetherListMixin,
    NoetherRetrieveMixin,
)
from noether.ledger.api.base import LedgerScopedMixin
from noether.ledger.models import Unit, UnitPrice
from noether.ledger.resources.price.spec import UnitPriceReadSpec, UnitPriceSpec
from noether.security.permissions.base import PricePermissions


class UnitPriceFilters(filters.FilterSet):
    unit = filters.CharFilter(field_name="unit__symbol")
    quote_unit = filters.CharFilter(field_name="quote_unit__symbol")
    as_of_before = filters.IsoDateTimeFilter(field_name="as_of", lookup_expr="lt")
    as_of_after = filters.IsoDateTimeFilter(field_name="as_of", lookup_expr="gt")


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
    filterset_class = UnitPriceFilters
    filter_backends = [filters.DjangoFilterBackend]

    def get_queryset(self):
        return (
            UnitPrice.objects.filter(ledger=self.get_ledger(), deleted=False)
            .select_related("unit", "quote_unit")
            .order_by("-as_of")
        )

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
