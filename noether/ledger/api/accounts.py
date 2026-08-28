import datetime

from django.utils.dateparse import parse_datetime
from pydantic import UUID4
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from noether.api.viewsets.base import NoetherModelViewSet
from noether.domains.registry import DomainRegistry
from noether.ledger.api.base import LedgerScopedMixin
from noether.ledger.models import Account, Unit
from noether.ledger.services.balances import (
    ValuationUnavailableError,
    get_balance,
    get_market_value,
)
from noether.resources.base import NoetherResource
from noether.security.permissions.base import (
    AccountPermissions,
    BalancePermissions,
    TransactionPermissions,
)


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


class AccountViewSet(LedgerScopedMixin, NoetherModelViewSet):
    database_model = Account
    pydantic_model = AccountSpec
    pydantic_read_model = AccountReadSpec
    pydantic_update_model = AccountUpdateSpec

    def get_queryset(self):
        queryset = (
            Account.objects.filter(ledger=self.get_ledger(), deleted=False)
            .select_related("unit", "parent")
            .order_by("-id")
        )
        params = self.request.query_params
        if params.get("parent"):
            queryset = queryset.filter(parent__external_id=params["parent"])
        if params.get("type"):
            queryset = queryset.filter(account_type=params["type"])
        if params.get("archived"):
            queryset = queryset.filter(archived=params["archived"] == "true")
        return queryset

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
        result = {
            "account": str(instance.external_id),
            "unit": instance.unit.symbol,
            "balance": str(get_balance(instance, as_of=as_of)),
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
            result["value_in"] = value_in
            result["market_value"] = str(market_value)
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
