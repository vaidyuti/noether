from decimal import Decimal

from django.utils.dateparse import parse_datetime
from django_filters import rest_framework as filters
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from noether.api.viewsets.base import NoetherModelViewSet
from noether.domains.registry import DomainRegistry
from noether.ledger.api.base import LedgerScopedMixin
from noether.ledger.models import Account, Unit
from noether.ledger.resources.account.spec import (
    AccountReadSpec,
    AccountSpec,
    AccountUpdateSpec,
)
from noether.ledger.services.balances import (
    ValuationUnavailableError,
    get_balance,
    get_market_value,
    get_raw_balance,
)
from noether.security.permissions.base import (
    AccountPermissions,
    BalancePermissions,
    TransactionPermissions,
)


class AccountFilters(filters.FilterSet):
    parent = filters.UUIDFilter(field_name="parent__external_id")
    type = filters.CharFilter(field_name="account_type")
    archived = filters.BooleanFilter(field_name="archived")


class AccountViewSet(LedgerScopedMixin, NoetherModelViewSet):
    database_model = Account
    pydantic_model = AccountSpec
    pydantic_read_model = AccountReadSpec
    pydantic_update_model = AccountUpdateSpec
    filterset_class = AccountFilters
    filter_backends = [filters.DjangoFilterBackend]

    def get_queryset(self):
        return (
            Account.objects.filter(ledger=self.get_ledger(), deleted=False)
            .select_related("unit", "parent")
            .order_by("-id")
        )

    def validate_data(self, instance, model_obj=None):
        if model_obj is not None:
            return
        ledger = self.get_ledger()
        config = DomainRegistry.get(ledger.domain.slug)
        type_names = {t.name for t in config.account_types}
        if instance.account_type not in type_names:
            raise ValidationError(
                f"account type {instance.account_type!r} is not registered "
                f"for domain {ledger.domain.slug!r}"
            )
        instance._unit_row = Unit.objects.filter(
            ledger=ledger, external_id=instance.unit, deleted=False
        ).first()
        if instance._unit_row is None:
            raise ValidationError("unknown unit")
        instance._parent_row = None
        if instance.parent is not None:
            instance._parent_row = Account.objects.filter(
                ledger=ledger, external_id=instance.parent, deleted=False
            ).first()
            if instance._parent_row is None:
                raise ValidationError("unknown parent account")

    def perform_create(self, instance):
        instance.ledger = self.get_ledger()
        super().perform_create(instance)

    def authorize_retrieve(self, model_instance):
        self.check_ledger_permission(AccountPermissions.account__read.name)

    def authorize_create(self, instance):
        self.check_ledger_permission(AccountPermissions.account__write.name)

    def authorize_update(self, request_obj, model_instance):
        self.check_ledger_permission(AccountPermissions.account__write.name)

    def list(self, request, *args, **kwargs):
        self.check_ledger_permission(AccountPermissions.account__read.name)
        return super().list(request, *args, **kwargs)

    @action(detail=True, methods=["POST"])
    def archive(self, request, *args, **kwargs):
        self.check_ledger_permission(AccountPermissions.account__archive.name)
        instance = self.get_object()
        instance.archived = True
        instance.updated_by = request.user
        instance.save(update_fields=["archived", "updated_by", "modified_date"])
        return Response(AccountReadSpec.serialize(instance).to_json())

    @action(detail=True, methods=["GET"])
    def balance(self, request, *args, **kwargs):
        self.check_ledger_permission(BalancePermissions.balance__read.name)
        instance = self.get_object()
        as_of = _parse_as_of(request)
        quantum = Decimal(1).scaleb(-instance.unit.precision)
        result = {
            "account": str(instance.external_id),
            "unit": instance.unit.symbol,
            "balance": str(get_balance(instance, as_of=as_of).quantize(quantum)),
            "raw_balance": str(get_raw_balance(instance, as_of=as_of).quantize(quantum)),
        }
        value_in = request.query_params.get("value_in")
        if value_in:
            quote_unit = Unit.objects.filter(
                ledger=instance.ledger, symbol=value_in, deleted=False
            ).first()
            if quote_unit is None:
                raise ValidationError(f"unknown unit {value_in!r}")
            try:
                market_value = get_market_value(instance, quote_unit, as_of=as_of)
            except ValuationUnavailableError as exc:
                raise ValidationError(str(exc)) from exc
            value_quantum = Decimal(1).scaleb(-quote_unit.precision)
            result["value_unit"] = value_in
            result["value"] = str(market_value.quantize(value_quantum))
        return Response(result)

    @action(detail=True, methods=["GET"])
    def entries(self, request, *args, **kwargs):
        self.check_ledger_permission(TransactionPermissions.transaction__read.name)
        instance = self.get_object()
        queryset = instance.entries.select_related("transaction").order_by("-id")
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        data = [
            {
                "id": str(entry.external_id),
                "transaction": str(entry.transaction.external_id),
                "direction": entry.direction,
                "amount": str(entry.amount),
                "metadata": entry.metadata,
            }
            for entry in page
        ]
        return paginator.get_paginated_response(data)


def _parse_as_of(request):
    raw = request.query_params.get("as_of")
    if not raw:
        return None
    parsed = parse_datetime(raw)
    if parsed is None:
        raise ValidationError(f"invalid as_of {raw!r}")
    return parsed
