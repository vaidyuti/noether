import datetime

from pydantic import UUID4

from noether.ledger.models import Unit
from noether.resources.base import NoetherResource


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
    id: UUID4 | None = None
    symbol: str = ""
    name: str = ""
    precision: int = 2
    metadata: dict = {}
    created_date: datetime.datetime | None = None
