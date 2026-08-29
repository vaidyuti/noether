import datetime

from pydantic import UUID4

from noether.ledger.models import Ledger
from noether.resources.base import NoetherResource, SlugStr


class LedgerCreateSpec(NoetherResource):
    __model__ = Ledger
    domain: str
    name: str
    slug: SlugStr | None = None
    description: str = ""
    settings: dict = {}
    chart_template: str | None = None


class LedgerUpdateSpec(NoetherResource):
    __model__ = Ledger
    name: str | None = None
    slug: SlugStr | None = None
    description: str | None = None
    settings: dict | None = None


class LedgerReadSpec(NoetherResource):
    __model__ = Ledger
    id: UUID4 | None = None
    name: str = ""
    slug: str | None = None
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
