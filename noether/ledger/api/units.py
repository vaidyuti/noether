from rest_framework.exceptions import ValidationError

from noether.api.viewsets.base import NoetherModelViewSet, NoetherUpsertMixin
from noether.ledger.api.base import LedgerScopedMixin
from noether.ledger.models import Unit
from noether.ledger.resources.unit.spec import UnitReadSpec, UnitSpec, UnitUpdateSpec
from noether.security.permissions.base import UnitPermissions


class UnitViewSet(LedgerScopedMixin, NoetherUpsertMixin, NoetherModelViewSet):
    database_model = Unit
    pydantic_model = UnitSpec
    pydantic_read_model = UnitReadSpec
    pydantic_update_model = UnitUpdateSpec

    def get_queryset(self):
        return Unit.objects.filter(ledger=self.get_ledger(), deleted=False).order_by("-id")

    def validate_data(self, instance, model_obj=None):
        if model_obj is None and (
            self.exclude_replay_target(
                Unit.objects.filter(ledger=self.get_ledger(), symbol=instance.symbol, deleted=False)
            ).exists()
        ):
            raise ValidationError(f"unit symbol {instance.symbol!r} already exists")
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
