import datetime

from pydantic import UUID4

from noether.ledger.models import Ledger
from noether.resources.base import NoetherResource


class LedgerCreateSpec(NoetherResource):
    __model__ = Ledger
    domain: str
    name: str
    description: str = ""
    settings: dict = {}
    chart_template: str | None = None

    def perform_extra_deserialization(self, is_update, obj):
        obj.domain = self._domain_row


class LedgerUpdateSpec(NoetherResource):
    __model__ = Ledger
    name: str | None = None
    description: str | None = None
    settings: dict | None = None


class LedgerReadSpec(NoetherResource):
    __model__ = Ledger
    id: UUID4 | None = None
    name: str = ""
    description: str = ""
    settings: dict = {}
    domain: str | None = None
    created_date: datetime.datetime | None = None
    modified_date: datetime.datetime | None = None

    @classmethod
    def perform_extra_serialization(cls, mapping, obj):
        super().perform_extra_serialization(mapping, obj)
        mapping["domain"] = obj.domain.slug
        mapping.pop("deleted", None)
