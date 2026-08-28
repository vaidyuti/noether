from datetime import UTC, datetime, timedelta
from decimal import Decimal

from django.test import TestCase

from noether.ledger.models import BalanceSnapshot, UnitPrice
from noether.ledger.services.balances import get_balance, get_market_value
from noether.ledger.tests.factories import (
    AccountFactory,
    LedgerFactory,
    UnitFactory,
    UserFactory,
    posted_transaction,
)
from tests.support import ensure_registered

T0 = datetime(2026, 1, 10, tzinfo=UTC)
T1 = datetime(2026, 1, 20, tzinfo=UTC)


class BalanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_registered()
        cls.user = UserFactory()
        cls.ledger = LedgerFactory()
        cls.unit = UnitFactory(ledger=cls.ledger, symbol="TU")
        cls.quote = UnitFactory(ledger=cls.ledger, symbol="QU")
        cls.a = AccountFactory(ledger=cls.ledger, unit=cls.unit)
        cls.b = AccountFactory(ledger=cls.ledger, unit=cls.unit)

    def post(self, amount, occurred_at=T0):
        return posted_transaction(
            ledger=self.ledger,
            debit_account=self.a,
            credit_account=self.b,
            amount=Decimal(amount),
            user=self.user,
            occurred_at=occurred_at,
        )

    def test_current_balance_zero_without_entries(self):
        self.assertEqual(get_balance(self.a), Decimal(0))

    def test_current_balance_materialized(self):
        self.post("10.00")
        self.post("5.00")
        self.assertEqual(get_balance(self.a), Decimal("15.00"))
        self.assertEqual(get_balance(self.b), Decimal("-15.00"))

    def test_as_of_replays_history(self):
        self.post("10.00", occurred_at=T0)
        self.post("7.00", occurred_at=T1)
        self.assertEqual(get_balance(self.a, as_of=T0 + timedelta(days=1)), Decimal("10.00"))
        self.assertEqual(get_balance(self.a, as_of=T1), Decimal("17.00"))
        self.assertEqual(get_balance(self.a, as_of=T0 - timedelta(days=1)), Decimal(0))

    def test_as_of_uses_snapshot_plus_replay(self):
        self.post("10.00", occurred_at=T0)
        BalanceSnapshot.objects.create(
            account=self.a,
            balance=Decimal("10.00"),
            as_of=T0 + timedelta(days=1),
        )
        self.post("7.00", occurred_at=T1)
        self.assertEqual(get_balance(self.a, as_of=T1), Decimal("17.00"))

    def test_market_value_same_unit_identity(self):
        self.post("10.00")
        self.assertEqual(get_market_value(self.a, value_in=self.unit), Decimal("10.00"))

    def test_market_value_uses_latest_price(self):
        self.post("10.00")
        UnitPrice.objects.create(
            ledger=self.ledger,
            unit=self.unit,
            quote_unit=self.quote,
            price=Decimal("2.0000000000"),
            as_of=T0,
            source="test",
        )
        UnitPrice.objects.create(
            ledger=self.ledger,
            unit=self.unit,
            quote_unit=self.quote,
            price=Decimal("3.0000000000"),
            as_of=T1,
            source="test",
        )
        self.assertEqual(get_market_value(self.a, value_in=self.quote), Decimal("30.00"))

    def test_market_value_as_of_picks_price_at_time(self):
        self.post("10.00", occurred_at=T0)
        UnitPrice.objects.create(
            ledger=self.ledger,
            unit=self.unit,
            quote_unit=self.quote,
            price=Decimal("2.0000000000"),
            as_of=T0,
            source="test",
        )
        UnitPrice.objects.create(
            ledger=self.ledger,
            unit=self.unit,
            quote_unit=self.quote,
            price=Decimal("3.0000000000"),
            as_of=T1,
            source="test",
        )
        value = get_market_value(self.a, value_in=self.quote, as_of=T0 + timedelta(days=1))
        self.assertEqual(value, Decimal("20.00"))

    def test_market_value_without_price_raises(self):
        self.post("10.00")
        with self.assertRaises(ValueError):
            get_market_value(self.a, value_in=self.quote)
