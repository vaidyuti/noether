from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class PriceQuote:
    unit_symbol: str
    quote_unit_symbol: str
    price: Decimal
    as_of: datetime
    source: str = ""


class ValuationStrategy:
    """Base class for domain price-feed hooks.

    ``schedule`` is a crontab string registered with celery-beat.
    ``fetch_prices(ledger)`` returns PriceQuote rows; core persists them.
    """

    schedule: str | None = None

    def fetch_prices(self, ledger) -> list[PriceQuote]:
        raise NotImplementedError
