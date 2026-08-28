import datetime

from pydantic import UUID4
from rest_framework.exceptions import ValidationError

from noether.api.viewsets.base import NoetherModelViewSet
from noether.ledger.api.base import LedgerScopedMixin
from noether.ledger.models import Unit
from noether.resources.base import NoetherResource
from noether.security.permissions.base import UnitPermissions


class UnitSpec(NoetherResource):
    __model__ = Unit
    symbol: str
    name: str
    precision: int = 2


class UnitUpdateSpec(NoetherResource):
    __model__ = Unit
    symbol: str | None = None
    name: str | None = None
    precision: int | None = None


class UnitReadSpec(NoetherResource):
    __model__ = Unit
    id: UUID4 | None = None
    symbol: str = ""
    name: str = ""
    precision: int = 2
    metadata: dict = {}
    created_date: datetime.datetime | None = None


class UnitViewSet(LedgerScopedMixin, NoetherModelViewSet):
    database_model = Unit
    pydantic_model = UnitSpec
    pydantic_read_model = UnitReadSpec
    pydantic_update_model = UnitUpdateSpec

    def get_queryset(self):
        return Unit.objects.filter(ledger=self.get_ledger(), deleted=False).order_by("-id")

    def validate_data(self, instance, model_obj=None):
        precision = instance.precision
        if precision is None:
            return
        if precision < 0 or precision > 10:
            raise ValidationError("precision must be between 0 and 10")
        if model_obj is None:
            return
        if precision == model_obj.precision:
            return
        if model_obj.accounts.filter(entries__isnull=False).exists():
            raise ValidationError("precision is immutable once the unit is used")

    def authorize_retrieve(self, model_instance):
        self.check_ledger_permission(UnitPermissions.unit__read.name)

    def authorize_create(self, instance):
        self.check_ledger_permission(UnitPermissions.unit__write.name)

    def authorize_update(self, request_obj, model_instance):
        self.check_ledger_permission(UnitPermissions.unit__write.name)

    def list(self, request, *args, **kwargs):
        self.check_ledger_permission(UnitPermissions.unit__read.name)
        return super().list(request, *args, **kwargs)

    def perform_create(self, instance):
        instance.ledger = self.get_ledger()
        super().perform_create(instance)
