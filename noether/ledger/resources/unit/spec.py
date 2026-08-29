import datetime

from noether.ledger.models import Unit
from noether.resources.base import ExternalId, NoetherResource


class UnitSpec(NoetherResource):
    __model__ = Unit
    symbol: str
    name: str
    precision: int = 2


class UnitUpdateSpec(NoetherResource):
    __model__ = Unit
    symbol: str | None = None
    name: str | None = None
    precision: int | None = None


class UnitReadSpec(NoetherResource):
    __model__ = Unit
    id: ExternalId | None = None
    symbol: str = ""
    name: str = ""
    precision: int = 2
    metadata: dict = {}
    created_date: datetime.datetime | None = None
