"""Hypothesis property suites — the six required properties (testing-standard)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase as HypothesisTestCase

from noether.ledger.exceptions import ConservationError, ImmutabilityError
from noether.ledger.models import BalanceSnapshot, TransactionStatus
from noether.ledger.services.balances import get_balance
from noether.ledger.services.posting import (
    EntryInput,
    create_transaction,
    post_transaction,
    reverse_transaction,
)
from noether.ledger.tests.factories import (
    AccountFactory,
    LedgerFactory,
    UnitFactory,
    UserFactory,
)
from tests.support import ensure_registered

BASE = datetime(2026, 1, 1, tzinfo=UTC)
FAST = settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

amounts = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


class PropertyBase(HypothesisTestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_registered()
        cls.user = UserFactory()
        cls.ledger = LedgerFactory()
        cls.unit = UnitFactory(ledger=cls.ledger, symbol="TU", precision=2)
        cls.accounts = [AccountFactory(ledger=cls.ledger, unit=cls.unit) for _ in range(4)]

    def make_entries(self, debits, credits):
        entries = []
        for i, amount in enumerate(debits):
            entries.append(
                EntryInput(account=self.accounts[i % 2], direction="debit", amount=amount)
            )
        for i, amount in enumerate(credits):
            entries.append(
                EntryInput(account=self.accounts[2 + i % 2], direction="credit", amount=amount)
            )
        return entries

    def try_post(self, entries, occurred_at=BASE):
        txn = create_transaction(
            ledger=self.ledger,
            description="prop",
            occurred_at=occurred_at,
            entries=entries,
            created_by=self.user,
        )
        return post_transaction(transaction=txn, posted_by=self.user)

    def balances(self):
        return [get_balance(account) for account in self.accounts]


class ConservationProperty(PropertyBase):
    @FAST
    @given(debits=st.lists(amounts, min_size=1, max_size=4))
    def test_balanced_always_posts(self, debits):
        total = sum(debits)
        txn = self.try_post(self.make_entries(debits, [total]))
        self.assertEqual(txn.status, TransactionStatus.POSTED)

    @FAST
    @given(
        debits=st.lists(amounts, min_size=1, max_size=4),
        skew=amounts,
    )
    def test_unbalanced_always_rejected(self, debits, skew):
        total = sum(debits) + skew
        with self.assertRaises(ConservationError):
            self.try_post(self.make_entries(debits, [total]))


class BalanceFoldProperty(PropertyBase):
    @FAST
    @given(seq=st.lists(amounts, min_size=1, max_size=6))
    def test_balance_equals_fold(self, seq):
        start = self.balances()
        for amount in seq:
            self.try_post(self.make_entries([amount], [amount]))
        self.assertEqual(get_balance(self.accounts[0]), start[0] + sum(seq))
        self.assertEqual(get_balance(self.accounts[2]), start[2] - sum(seq))


class ReversalRoundTripProperty(PropertyBase):
    @FAST
    @given(seq=st.lists(amounts, min_size=1, max_size=4))
    def test_reverse_restores_pre_state(self, seq):
        pre = self.balances()
        posted = [self.try_post(self.make_entries([amount], [amount])) for amount in seq]
        for txn in reversed(posted):
            reverse_transaction(transaction=txn, reversed_by=self.user)
        self.assertEqual(self.balances(), pre)


class SnapshotEquivalenceProperty(PropertyBase):
    @FAST
    @given(
        seq=st.lists(amounts, min_size=2, max_size=6),
        cut=st.integers(min_value=1, max_value=5),
    )
    def test_snapshot_replay_equals_fold(self, seq, cut):
        cut = min(cut, len(seq) - 1)
        account = self.accounts[0]
        for i, amount in enumerate(seq):
            self.try_post(
                self.make_entries([amount], [amount]),
                occurred_at=BASE + timedelta(days=i),
            )
        as_of = BASE + timedelta(days=len(seq))
        expected = get_balance(account, as_of=as_of)
        BalanceSnapshot.objects.create(
            account=account,
            balance=get_balance(account, as_of=BASE + timedelta(days=cut - 1)),
            as_of=BASE + timedelta(days=cut - 1),
        )
        self.assertEqual(get_balance(account, as_of=as_of), expected)
        BalanceSnapshot.objects.all().delete()


class PrecisionProperty(PropertyBase):
    @FAST
    @given(
        amount=st.decimals(
            min_value=Decimal("0.001"),
            max_value=Decimal("999.999"),
            places=3,
            allow_nan=False,
            allow_infinity=False,
        ).filter(lambda d: d % Decimal("0.01") != 0)
    )
    def test_precision_violations_always_rejected(self, amount):
        with self.assertRaises(ConservationError):
            self.try_post(self.make_entries([amount], [amount]))


class ImmutabilityProperty(PropertyBase):
    @FAST
    @given(amount=amounts, new_amount=amounts)
    def test_posted_mutation_always_raises_state_unchanged(self, amount, new_amount):
        txn = self.try_post(self.make_entries([amount], [amount]))
        pre = self.balances()
        entry = txn.entries.first()
        entry.amount = new_amount
        with self.assertRaises(ImmutabilityError):
            entry.save()
        txn.description = "mutated"
        with self.assertRaises(ImmutabilityError):
            txn.save()
        with self.assertRaises(ImmutabilityError):
            txn.delete()
        self.assertEqual(self.balances(), pre)
