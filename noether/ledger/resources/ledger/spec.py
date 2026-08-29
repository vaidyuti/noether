import datetime

from noether.extensions.base import ExtensionResource
from noether.extensions.validator import (
    ExtensionListRenderer,
    ExtensionRetrieveRenderer,
    ExtensionValidator,
)
from noether.ledger.models import Ledger
from noether.resources.base import ExternalId, NoetherResource, SlugStr


class LedgerCreateSpec(ExtensionValidator, NoetherResource):
    __model__ = Ledger
    __extension_resource__ = ExtensionResource.ledger
    domain: str
    name: str
    slug: SlugStr | None = None
    description: str = ""
    settings: dict = {}
    chart_template: str | None = None


class LedgerUpdateSpec(ExtensionValidator, NoetherResource):
    __model__ = Ledger
    __extension_resource__ = ExtensionResource.ledger
    name: str | None = None
    slug: SlugStr | None = None
    description: str | None = None
    settings: dict | None = None


class LedgerReadSpec(ExtensionListRenderer, NoetherResource):
    __model__ = Ledger
    __extension_resource__ = ExtensionResource.ledger
    id: ExternalId | None = None
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


class LedgerRetrieveSpec(ExtensionRetrieveRenderer, LedgerReadSpec):
    pass
