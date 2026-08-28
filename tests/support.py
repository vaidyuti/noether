"""Sample in-tests-only DomainConfig exercising the whole plugin contract."""

from datetime import UTC, datetime
from decimal import Decimal

from noether.domains.config import (
    AccountTypeDef,
    ChartNode,
    ChartTemplate,
    DomainConfig,
    UnitDef,
)
from noether.domains.registry import DomainRegistry
from noether.domains.validators import TransactionValidator
from noether.domains.valuation import PriceQuote, ValuationStrategy
from noether.ledger.exceptions import DomainValidationError


class NonNegativeBalances(TransactionValidator):
    """Accounts flagged metadata.non_negative cannot go below zero."""

    def validate(self, transaction, entries, balances_after) -> None:
        for entry in entries:
            flagged = entry.account.metadata.get("non_negative")
            if not flagged:
                continue
            if balances_after[entry.account_id] < 0:
                raise DomainValidationError(f"{entry.account.name} cannot go negative")


class StaticPriceFetcher(ValuationStrategy):
    schedule = "0 18 * * 1-5"

    def fetch_prices(self, ledger) -> list[PriceQuote]:
        return [
            PriceQuote(
                unit_symbol="TU",
                quote_unit_symbol="QU",
                price=Decimal("2.5"),
                as_of=datetime(2026, 1, 1, tzinfo=UTC),
                source="static",
            )
        ]


TEST_DOMAIN = DomainConfig(
    slug="testdomain",
    name="Test Domain",
    version="1.0.0",
    account_types=[
        AccountTypeDef(name="generic", normal_balance="debit"),
        AccountTypeDef(name="boundary", normal_balance="credit"),
    ],
    default_units=[
        UnitDef(symbol="TU", name="Test Unit", precision=2),
        UnitDef(symbol="QU", name="Quote Unit", precision=2),
    ],
    chart_templates=[
        ChartTemplate(
            name="default",
            nodes=[
                ChartNode(path="Stores", account_type="generic", unit="TU", placeholder=True),
                ChartNode(path="Stores/Main", account_type="generic", unit="TU"),
                ChartNode(path="Boundary/World", account_type="boundary", unit="TU"),
                ChartNode(path="Quoted", account_type="generic", unit="QU"),
            ],
        )
    ],
    validators=[NonNegativeBalances()],
    valuation=StaticPriceFetcher(),
)


def ensure_registered() -> None:
    if "testdomain" not in [c.slug for c in DomainRegistry.all()]:
        DomainRegistry.register(TEST_DOMAIN)


ensure_registered()
