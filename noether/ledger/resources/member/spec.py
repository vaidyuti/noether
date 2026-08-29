import datetime

from noether.resources.base import ExternalId, NoetherResource
from noether.security.models import LedgerUser


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
    id: ExternalId | None = None
    user: str | None = None
    role: str | None = None
    created_date: datetime.datetime | None = None

    @classmethod
    def perform_extra_serialization(cls, mapping, obj):
        super().perform_extra_serialization(mapping, obj)
        mapping["user"] = obj.user.username
        mapping["role"] = obj.role.name
