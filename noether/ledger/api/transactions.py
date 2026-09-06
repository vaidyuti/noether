from decimal import Decimal

from django_filters import rest_framework as filters
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from noether.api.viewsets.base import NoetherModelViewSet
from noether.api.viewsets.tags import TagMixin
from noether.ledger.api.base import LedgerScopedMixin
from noether.ledger.exceptions import ExternalIdConflictError, ImmutabilityError
from noether.ledger.models import Account, Transaction
from noether.ledger.resources.tag.constants import TagResource
from noether.ledger.resources.transaction.constants import TransactionStatus
from noether.ledger.resources.transaction.spec import (
    ReverseSpec,
    TransactionCreateSpec,
    TransactionReadSpec,
    TransactionRetrieveSpec,
    TransactionUpdateSpec,
)
from noether.ledger.services.posting import (
    EntryInput,
    create_transaction,
    post_transaction,
    reverse_transaction,
)
from noether.security.permissions.base import TagPermissions, TransactionPermissions
from noether.tagging.filters import TagFilter


class TransactionFilters(filters.FilterSet):
    status = filters.CharFilter(field_name="status")
    account = filters.UUIDFilter(method="filter_account")
    occurred_after = filters.IsoDateTimeFilter(field_name="occurred_at", lookup_expr="gt")
    occurred_before = filters.IsoDateTimeFilter(field_name="occurred_at", lookup_expr="lt")
    tags = TagFilter()
    tags_all = TagFilter(behavior="all")

    def filter_account(self, queryset, name, value):
        return queryset.filter(entries__account__external_id=value).distinct()


class TransactionViewSet(TagMixin, LedgerScopedMixin, NoetherModelViewSet):
    database_model = Transaction
    pydantic_model = TransactionCreateSpec
    pydantic_read_model = TransactionReadSpec
    pydantic_update_model = TransactionUpdateSpec
    pydantic_retrieve_model = TransactionRetrieveSpec
    filterset_class = TransactionFilters
    filter_backends = [filters.DjangoFilterBackend]
    tag_resource_type = TagResource.transaction

    def authorize_tag(self, instance):
        self.check_ledger_permission(TagPermissions.tag__apply.name)

    def get_queryset(self):
        return Transaction.objects.filter(ledger=self.get_ledger(), deleted=False).order_by("-id")

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

    def _replay_fingerprint(self, description, occurred_at, entries, metadata):
        """Canonical form of a transaction create, for replay comparison.

        Entry *order* is significant: entries are an ordered list in both the
        request and the stored transaction, and a client that reorders them has
        described a different transaction, not replayed the same one.
        """
        return {
            "description": description,
            "occurred_at": occurred_at.isoformat() if occurred_at else None,
            "metadata": metadata or {},
            "entries": [
                {
                    "account": str(account),
                    "direction": str(direction),
                    "amount": str(Decimal(amount).normalize()),
                    "metadata": entry_metadata or {},
                }
                for account, direction, amount, entry_metadata in entries
            ],
        }

    def _spec_fingerprint(self, spec):
        return self._replay_fingerprint(
            spec.description,
            spec.occurred_at,
            [(e.account, e.direction, e.amount, e.metadata) for e in spec.entries],
            spec.metadata,
        )

    def _stored_fingerprint(self, txn):
        return self._replay_fingerprint(
            txn.description,
            txn.occurred_at,
            [
                (entry.account.external_id, entry.direction, entry.amount, entry.metadata)
                for entry in txn.entries.select_related("account").order_by("id")
            ],
            txn.metadata,
        )

    def create(self, request, *args, **kwargs):
        self.check_ledger_permission(TransactionPermissions.transaction__create.name)
        external_id = self.extract_client_external_id(request.data)
        spec = TransactionCreateSpec.model_validate(request.data)
        if spec.post:
            self.check_ledger_permission(TransactionPermissions.transaction__post.name)
        if external_id is not None:
            existing = self.find_replay_target(external_id)
            if existing is not None:
                # Authorization already ran above, so a replay is no cheaper
                # than the original write and leaks nothing extra.
                if self._stored_fingerprint(existing) != self._spec_fingerprint(spec):
                    raise ExternalIdConflictError(
                        f"id {external_id} already identifies a different transaction"
                    )
                return Response(TransactionReadSpec.serialize(existing).to_json())
        txn = create_transaction(
            ledger=self.get_ledger(),
            description=spec.description,
            occurred_at=spec.occurred_at,
            entries=self._resolve_entries(spec),
            metadata=spec.metadata,
            created_by=request.user,
            external_id=external_id,
        )
        if spec.extensions:
            txn.extensions = spec.extensions
            txn.save(update_fields=["extensions", "modified_date"])
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
