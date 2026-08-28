import datetime
from decimal import Decimal

from django.utils.dateparse import parse_datetime
from pydantic import UUID4, BaseModel, field_validator
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from noether.api.viewsets.base import NoetherModelViewSet
from noether.ledger.api.base import LedgerScopedMixin
from noether.ledger.exceptions import ImmutabilityError
from noether.ledger.models import Account, EntryDirection, Transaction, TransactionStatus
from noether.ledger.services.posting import (
    EntryInput,
    create_transaction,
    post_transaction,
    reverse_transaction,
)
from noether.resources.base import NoetherResource
from noether.security.permissions.base import TransactionPermissions


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


class TransactionViewSet(LedgerScopedMixin, NoetherModelViewSet):
    database_model = Transaction
    pydantic_model = TransactionCreateSpec
    pydantic_read_model = TransactionReadSpec
    pydantic_update_model = TransactionUpdateSpec

    def get_queryset(self):
        queryset = Transaction.objects.filter(ledger=self.get_ledger(), deleted=False).order_by(
            "-id"
        )
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status=params["status"])
        if params.get("account"):
            queryset = queryset.filter(entries__account__external_id=params["account"]).distinct()
        if params.get("occurred_after"):
            queryset = queryset.filter(occurred_at__gt=_parse_dt(params["occurred_after"]))
        if params.get("occurred_before"):
            queryset = queryset.filter(occurred_at__lt=_parse_dt(params["occurred_before"]))
        return queryset

    def list(self, request, *args, **kwargs):
        self.check_ledger_permission(TransactionPermissions.transaction__read.name)
        return super().list(request, *args, **kwargs)

    def authorize_retrieve(self, model_instance):
        self.check_ledger_permission(TransactionPermissions.transaction__read.name)

    def _resolve_entries(self, spec: TransactionCreateSpec) -> "list[EntryInput]":
        ledger = self.get_ledger()
        inputs = []
        for entry in spec.entries:
            account = Account.objects.filter(
                ledger=ledger, external_id=entry.account, deleted=False
            ).first()
            if account is None:
                raise ValidationError(f"unknown account {entry.account}")
            inputs.append(
                EntryInput(
                    account=account,
                    direction=entry.direction,
                    amount=entry.amount,
                    metadata=entry.metadata,
                )
            )
        return inputs

    def create(self, request, *args, **kwargs):
        self.check_ledger_permission(TransactionPermissions.transaction__create.name)
        spec = TransactionCreateSpec.model_validate(request.data)
        if spec.post:
            self.check_ledger_permission(TransactionPermissions.transaction__post.name)
        txn = create_transaction(
            ledger=self.get_ledger(),
            description=spec.description,
            occurred_at=spec.occurred_at,
            entries=self._resolve_entries(spec),
            metadata=spec.metadata,
            created_by=request.user,
        )
        if spec.post:
            txn = post_transaction(transaction=txn, posted_by=request.user)
        return Response(TransactionReadSpec.serialize(txn).to_json(), status=201)

    def validate_data(self, instance, model_obj=None):
        if model_obj is not None and model_obj.status != TransactionStatus.DRAFT:
            raise ImmutabilityError(
                f"transaction {model_obj.external_id} is {model_obj.status} and immutable"
            )

    def authorize_update(self, request_obj, model_instance):
        self.check_ledger_permission(TransactionPermissions.transaction__write.name)

    def validate_destroy(self, instance):
        if instance.status != TransactionStatus.DRAFT:
            raise ImmutabilityError(
                f"transaction {instance.external_id} is {instance.status} and cannot be deleted"
            )

    def authorize_destroy(self, instance):
        self.check_ledger_permission(TransactionPermissions.transaction__delete.name)

    def perform_destroy(self, instance):
        instance.delete()

    @action(detail=True, methods=["POST"], url_path="post")
    def post_action(self, request, *args, **kwargs):
        self.check_ledger_permission(TransactionPermissions.transaction__post.name)
        instance = self.get_object()
        txn = post_transaction(transaction=instance, posted_by=request.user)
        return Response(TransactionReadSpec.serialize(txn).to_json())

    @action(detail=True, methods=["POST"])
    def reverse(self, request, *args, **kwargs):
        self.check_ledger_permission(TransactionPermissions.transaction__reverse.name)
        instance = self.get_object()
        spec = ReverseSpec.model_validate(request.data)
        mirror = reverse_transaction(
            transaction=instance,
            reversed_by=request.user,
            description=spec.description,
            occurred_at=spec.occurred_at,
        )
        return Response(TransactionReadSpec.serialize(mirror).to_json())


def _parse_dt(raw: str) -> datetime.datetime:
    parsed = parse_datetime(raw)
    if parsed is None:
        raise ValidationError(f"invalid datetime {raw!r}")
    return parsed
