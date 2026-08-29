from rest_framework.exceptions import ValidationError

from noether.api.viewsets.base import NoetherModelViewSet
from noether.ledger.api.base import LedgerScopedMixin
from noether.ledger.models import TagConfig
from noether.ledger.resources.tag.spec import (
    TagConfigReadSpec,
    TagConfigUpdateSpec,
    TagConfigWriteSpec,
)
from noether.security.permissions.base import TagPermissions


class TagConfigViewSet(LedgerScopedMixin, NoetherModelViewSet):
    database_model = TagConfig
    pydantic_model = TagConfigWriteSpec
    pydantic_read_model = TagConfigReadSpec
    pydantic_update_model = TagConfigUpdateSpec

    def get_queryset(self):
        return TagConfig.objects.filter(ledger=self.get_ledger(), deleted=False).order_by("-id")

    def list(self, request, *args, **kwargs):
        self.check_ledger_permission(TagPermissions.tag__read.name)
        return super().list(request, *args, **kwargs)

    def authorize_retrieve(self, model_instance):
        self.check_ledger_permission(TagPermissions.tag__read.name)

    def authorize_create(self, instance):
        self.check_ledger_permission(TagPermissions.tag__write.name)

    def authorize_update(self, request_obj, model_instance):
        self.check_ledger_permission(TagPermissions.tag__write.name)

    def authorize_destroy(self, instance):
        self.check_ledger_permission(TagPermissions.tag__write.name)

    def validate_data(self, instance, model_obj=None):
        if model_obj is not None:
            return
        instance._parent_row = None
        if instance.parent is None:
            return
        parent = TagConfig.objects.filter(
            ledger=self.get_ledger(), external_id=instance.parent, deleted=False
        ).first()
        if parent is None:
            raise ValidationError(f"unknown parent tag {instance.parent} in this ledger")
        if parent.resource != instance.resource:
            raise ValidationError("parent tag config resource mismatch")
        instance._parent_row = parent

    def perform_create(self, instance):
        instance.ledger = self.get_ledger()
        super().perform_create(instance)
