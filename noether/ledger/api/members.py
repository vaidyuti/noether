import datetime

from pydantic import UUID4
from rest_framework.exceptions import ValidationError

from noether.api.viewsets.base import NoetherModelViewSet
from noether.ledger.api.base import LedgerScopedMixin
from noether.resources.base import NoetherResource
from noether.security.models import LedgerUser
from noether.security.models import Role as RoleModel
from noether.security.permissions.base import LedgerPermissions
from noether.users.models import User


class MemberSpec(NoetherResource):
    __model__ = LedgerUser
    user: str
    role: str

    def perform_extra_deserialization(self, is_update, obj):
        obj.role = self._role_row
        obj.user = self._user_row


class MemberUpdateSpec(NoetherResource):
    __model__ = LedgerUser
    role: str

    def perform_extra_deserialization(self, is_update, obj):
        obj.role = self._role_row


class MemberReadSpec(NoetherResource):
    __model__ = LedgerUser
    id: UUID4 | None = None
    user: str | None = None
    role: str | None = None
    created_date: datetime.datetime | None = None

    @classmethod
    def perform_extra_serialization(cls, mapping, obj):
        super().perform_extra_serialization(mapping, obj)
        mapping["user"] = obj.user.username
        mapping["role"] = obj.role.name


class LedgerUserViewSet(LedgerScopedMixin, NoetherModelViewSet):
    database_model = LedgerUser
    pydantic_model = MemberSpec
    pydantic_read_model = MemberReadSpec
    pydantic_update_model = MemberUpdateSpec

    def get_queryset(self):
        return (
            LedgerUser.objects.filter(ledger=self.get_ledger(), deleted=False)
            .select_related("user", "role")
            .order_by("-id")
        )

    def list(self, request, *args, **kwargs):
        self.check_ledger_permission(LedgerPermissions.ledger__read.name)
        return super().list(request, *args, **kwargs)

    def authorize_retrieve(self, model_instance):
        self.check_ledger_permission(LedgerPermissions.ledger__read.name)

    def authorize_create(self, instance):
        self.check_ledger_permission(LedgerPermissions.ledger__manage_members.name)

    def authorize_update(self, request_obj, model_instance):
        self.check_ledger_permission(LedgerPermissions.ledger__manage_members.name)

    def authorize_destroy(self, instance):
        self.check_ledger_permission(LedgerPermissions.ledger__manage_members.name)

    def _resolve_role(self, name):
        role = RoleModel.objects.filter(name=name).first()
        if role is None:
            raise ValidationError(f"unknown role {name!r}")
        return role

    def validate_data(self, instance, model_obj=None):
        instance._role_row = self._resolve_role(instance.role)
        if model_obj is not None:
            return
        instance._user_row = User.objects.filter(username=instance.user).first()
        if instance._user_row is None:
            raise ValidationError(f"unknown user {instance.user!r}")
        if LedgerUser.objects.filter(
            ledger=self.get_ledger(), user=instance._user_row, deleted=False
        ).exists():
            raise ValidationError("user is already a member of this ledger")

    def perform_create(self, instance):
        instance.ledger = self.get_ledger()
        super().perform_create(instance)

    def perform_destroy(self, instance):
        instance.delete()
