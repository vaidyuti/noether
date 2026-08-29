from datetime import datetime, timedelta

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from noether.ledger.exceptions import ImmutabilityError
from noether.ledger.models_base import NoetherBaseModel, SluggedModel
from noether.tagging.models import TaggableMixin


class TransactionStatus(models.TextChoices):
    DRAFT = "draft"
    POSTED = "posted"
    REVERSED = "reversed"


class EntryDirection(models.TextChoices):
    DEBIT = "debit"
    CREDIT = "credit"


class Domain(NoetherBaseModel):
    slug = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=255)
    version = models.CharField(max_length=32)
    enabled = models.BooleanField(default=True)


class Ledger(SluggedModel, NoetherBaseModel):
    SLUG_SCOPE_FIELDS = ()

    domain = models.ForeignKey(Domain, on_delete=models.PROTECT, related_name="ledgers")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    settings = models.JSONField(default=dict, blank=True)
    extensions = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["slug"], name="unique_ledger_slug"),
        ]


class Unit(NoetherBaseModel):
    ledger = models.ForeignKey(Ledger, on_delete=models.CASCADE, related_name="units")
    symbol = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    precision = models.PositiveSmallIntegerField(default=2)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["ledger", "symbol"], name="unique_unit_per_ledger"),
        ]


class Account(SluggedModel, NoetherBaseModel):
    SLUG_SCOPE_FIELDS = ("ledger",)

    ledger = models.ForeignKey(Ledger, on_delete=models.CASCADE, related_name="accounts")
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=64)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="accounts")
    is_placeholder = models.BooleanField(default=False)
    archived = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    extensions = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ledger", "slug"], name="unique_account_slug_per_ledger"
            ),
        ]


class Transaction(TaggableMixin, NoetherBaseModel):
    ledger = models.ForeignKey(Ledger, on_delete=models.CASCADE, related_name="transactions")
    status = models.CharField(
        max_length=16, choices=TransactionStatus.choices, default=TransactionStatus.DRAFT
    )
    description = models.TextField(blank=True, default="")
    occurred_at = models.DateTimeField()
    posted_at = models.DateTimeField(null=True, blank=True)
    reverses = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    reversed_by = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    metadata = models.JSONField(default=dict, blank=True)
    extensions = models.JSONField(default=dict, blank=True)

    ALLOWED_POSTED_TRANSITIONS = frozenset(
        ["reversed_by", "status", "modified_date", "updated_by", "tags"]
    )

    def save(self, *args, **kwargs):
        if self.pk is None:
            return super().save(*args, **kwargs)
        current = Transaction.objects.get(pk=self.pk)
        if current.status == TransactionStatus.DRAFT:
            return super().save(*args, **kwargs)
        changed = _changed_fields(current, self)
        if (
            current.status == TransactionStatus.POSTED
            and changed <= self.ALLOWED_POSTED_TRANSITIONS
        ):
            # the only legal posted-state mutation: being reversed
            return super().save(*args, **kwargs)
        raise ImmutabilityError(f"transaction {self.external_id} is {current.status} and immutable")

    def delete(self, *args, **kwargs):
        if self.status != TransactionStatus.DRAFT:
            raise ImmutabilityError(
                f"transaction {self.external_id} is {self.status} and cannot be deleted"
            )
        return super().delete(*args, **kwargs)


def _changed_fields(current: Transaction, new: Transaction) -> set[str]:
    changed = set()
    for field in Transaction._meta.concrete_fields:
        if field.name == "modified_date":
            continue
        if getattr(current, field.attname) != getattr(new, field.attname):
            changed.add(field.name)
    return changed


class Entry(NoetherBaseModel):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="entries")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="entries")
    direction = models.CharField(max_length=8, choices=EntryDirection.choices)
    amount = models.DecimalField(max_digits=30, decimal_places=10)
    metadata = models.JSONField(default=dict, blank=True)

    def save(self, *args, **kwargs):
        self._guard_immutable("modified")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._guard_immutable("deleted")
        return super().delete(*args, **kwargs)

    def _guard_immutable(self, verb: str):
        if self.pk is None:
            return
        status = Transaction.objects.get(pk=self.transaction_id).status
        if status != TransactionStatus.DRAFT:
            raise ImmutabilityError(f"entries of {status} transactions cannot be {verb}")


class AccountBalance(NoetherBaseModel):
    account = models.OneToOneField(Account, on_delete=models.CASCADE, related_name="balance_row")
    balance = models.DecimalField(max_digits=30, decimal_places=10)


class BalanceSnapshot(NoetherBaseModel):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="snapshots")
    as_of = models.DateTimeField(db_index=True)
    balance = models.DecimalField(max_digits=30, decimal_places=10)


class UnitPrice(NoetherBaseModel):
    ledger = models.ForeignKey(Ledger, on_delete=models.CASCADE, related_name="prices")
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="prices")
    quote_unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="quoted_prices")
    price = models.DecimalField(max_digits=30, decimal_places=10)
    as_of = models.DateTimeField(db_index=True)
    source = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)


class TagConfig(NoetherBaseModel):
    """A tag definition, scoped to a single ledger (ADR-0013).

    ``exclusive_children`` is the configurable exclusivity rule: when a tag
    config sets it, at most ONE tag from that config's subtree may be applied
    to any given tagged row. When it is false, siblings coexist freely.
    """

    #: How long a materialized ``cached_parent_json`` blob stays fresh.
    CACHE_EXPIRY_DAYS = 15

    ledger = models.ForeignKey(Ledger, on_delete=models.CASCADE, related_name="tag_configs")
    display = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    status = models.CharField(max_length=32, default="active")
    resource = models.CharField(max_length=64)
    parent = models.ForeignKey(
        "self", related_name="children", on_delete=models.CASCADE, null=True, blank=True
    )
    root_tag_config = models.ForeignKey(
        "self", related_name="descendants", on_delete=models.CASCADE, null=True, blank=True
    )
    level_cache = models.IntegerField(default=0)
    parent_cache = ArrayField(models.IntegerField(), default=list, blank=True)
    cached_parent_json = models.JSONField(default=dict, blank=True)
    has_children = models.BooleanField(default=False)
    exclusive_children = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)

    def refresh_hierarchy_cache(self):
        """Materialize ancestry caches for a freshly created config."""
        if self.parent_id is None:
            return
        parent = self.parent
        self.parent_cache = [*parent.parent_cache, parent.id]
        self.level_cache = parent.level_cache + 1
        self.root_tag_config = parent.root_tag_config or parent
        super().save(
            update_fields=["parent_cache", "level_cache", "root_tag_config", "modified_date"]
        )
        if not parent.has_children:
            parent.has_children = True
            parent.save(update_fields=["has_children", "modified_date"])

    def get_parent_json(self):
        """Return the (cached) denormalized ancestry blob for this config."""
        if self.parent_id is None:
            return {}
        if self.cached_parent_json and timezone.now() < datetime.fromisoformat(
            self.cached_parent_json["cache_expiry"]
        ):
            return self.cached_parent_json
        self.cached_parent_json = {
            "id": str(self.parent.external_id),
            "display": self.parent.display,
            "description": self.parent.description,
            "level_cache": self.parent.level_cache,
            "parent": self.parent.get_parent_json(),
            "cache_expiry": (timezone.now() + timedelta(days=self.CACHE_EXPIRY_DAYS)).isoformat(),
        }
        super().save(update_fields=["cached_parent_json", "modified_date"])
        return self.cached_parent_json

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        if creating:
            self.refresh_hierarchy_cache()
