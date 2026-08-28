from datetime import UTC, datetime
from decimal import Decimal

from django.test import TestCase

from noether.ledger.exceptions import ConservationError, DomainValidationError, ImmutabilityError
from noether.ledger.models import (
    AccountBalance,
    Entry,
    EntryDirection,
    Transaction,
    TransactionStatus,
)
from noether.ledger.services.balances import get_balance
from noether.ledger.services.posting import (
    EntryInput,
    create_transaction,
    post_transaction,
    reverse_transaction,
)
from noether.ledger.tests.factories import (
    AccountFactory,
    EntryFactory,
    LedgerFactory,
    TransactionFactory,
    UnitFactory,
    UserFactory,
    posted_transaction,
)
from tests.support import ensure_registered

OCCURRED = datetime(2026, 1, 15, tzinfo=UTC)


class PostingTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_registered()
        cls.user = UserFactory()
        cls.ledger = LedgerFactory()
        cls.unit = UnitFactory(ledger=cls.ledger, symbol="TU", precision=2)
        cls.a = AccountFactory(ledger=cls.ledger, unit=cls.unit, name="A")
        cls.b = AccountFactory(ledger=cls.ledger, unit=cls.unit, name="B")

    def draft(self, amount="100.00", debit=None, credit=None):
        return create_transaction(
            ledger=self.ledger,
            description="test",
            occurred_at=OCCURRED,
            entries=[
                EntryInput(
                    account=debit or self.a,
                    direction=EntryDirection.DEBIT,
                    amount=Decimal(amount),
                ),
                EntryInput(
                    account=credit or self.b,
                    direction=EntryDirection.CREDIT,
                    amount=Decimal(amount),
                ),
            ],
            created_by=self.user,
        )


class CreateTransactionTests(PostingTestBase):
    def test_creates_draft_with_entries(self):
        txn = self.draft()
        self.assertEqual(txn.status, TransactionStatus.DRAFT)
        self.assertEqual(txn.entries.count(), 2)
        self.assertEqual(txn.metadata, {})

    def test_metadata_persisted(self):
        txn = create_transaction(
            ledger=self.ledger,
            description="m",
            occurred_at=OCCURRED,
            entries=[
                EntryInput(
                    account=self.a,
                    direction=EntryDirection.DEBIT,
                    amount=Decimal("1.00"),
                    metadata={"k": "v"},
                ),
                EntryInput(account=self.b, direction=EntryDirection.CREDIT, amount=Decimal("1.00")),
            ],
            metadata={"note": "x"},
            created_by=self.user,
        )
        self.assertEqual(txn.metadata, {"note": "x"})
        self.assertEqual(txn.entries.get(direction="debit").metadata, {"k": "v"})

    def test_rejects_foreign_ledger_account(self):
        other = AccountFactory()
        with self.assertRaises(ConservationError):
            self.draft(debit=other)

    def test_rejects_placeholder_account(self):
        placeholder = AccountFactory(ledger=self.ledger, unit=self.unit, is_placeholder=True)
        with self.assertRaises(ConservationError):
            self.draft(debit=placeholder)

    def test_rejects_zero_amount(self):
        with self.assertRaises(ConservationError):
            self.draft(amount="0.00")

    def test_rejects_negative_amount(self):
        with self.assertRaises(ConservationError):
            self.draft(amount="-5.00")

    def test_rejects_precision_violation(self):
        with self.assertRaises(ConservationError):
            self.draft(amount="1.001")

    def test_draft_does_not_affect_balances(self):
        self.draft()
        self.assertEqual(get_balance(self.a), Decimal(0))


class PostTransactionTests(PostingTestBase):
    def test_post_updates_balances(self):
        txn = post_transaction(transaction=self.draft(), posted_by=self.user)
        self.assertEqual(txn.status, TransactionStatus.POSTED)
        self.assertIsNotNone(txn.posted_at)
        self.assertEqual(get_balance(self.a), Decimal("100.00"))
        self.assertEqual(get_balance(self.b), Decimal("-100.00"))

    def test_unbalanced_rejected_with_message(self):
        txn = TransactionFactory(ledger=self.ledger, occurred_at=OCCURRED)
        EntryFactory(transaction=txn, account=self.a, direction="debit", amount=Decimal("500.00"))
        EntryFactory(transaction=txn, account=self.b, direction="credit", amount=Decimal("400.00"))
        with self.assertRaises(ConservationError) as ctx:
            post_transaction(transaction=txn, posted_by=self.user)
        self.assertEqual(str(ctx.exception), "unit TU: debits 500.00 != credits 400.00")

    def test_minimum_arity(self):
        txn = TransactionFactory(ledger=self.ledger, occurred_at=OCCURRED)
        EntryFactory(transaction=txn, account=self.a, direction="debit", amount=Decimal("5.00"))
        with self.assertRaises(ConservationError):
            post_transaction(transaction=txn, posted_by=self.user)

    def test_repost_rejected(self):
        txn = post_transaction(transaction=self.draft(), posted_by=self.user)
        with self.assertRaises(ImmutabilityError):
            post_transaction(transaction=txn, posted_by=self.user)

    def test_archived_account_rejected_at_post(self):
        txn = self.draft()
        self.a.archived = True
        self.a.save()
        with self.assertRaises(ConservationError):
            post_transaction(transaction=txn, posted_by=self.user)

    def test_post_rejects_entry_mutated_below_zero(self):
        txn = self.draft()
        Entry.objects.filter(transaction=txn, direction="debit").update(amount=Decimal("-1"))
        Entry.objects.filter(transaction=txn, direction="credit").update(amount=Decimal("-1"))
        with self.assertRaises(ConservationError):
            post_transaction(transaction=txn, posted_by=self.user)

    def test_post_rejects_precision_mutated(self):
        txn = self.draft()
        Entry.objects.filter(transaction=txn).update(amount=Decimal("1.001"))
        with self.assertRaises(ConservationError):
            post_transaction(transaction=txn, posted_by=self.user)

    def test_per_unit_balancing_multi_unit(self):
        unit2 = UnitFactory(ledger=self.ledger, symbol="XU", precision=2)
        c = AccountFactory(ledger=self.ledger, unit=unit2)
        d = AccountFactory(ledger=self.ledger, unit=unit2)
        txn = create_transaction(
            ledger=self.ledger,
            description="cross",
            occurred_at=OCCURRED,
            entries=[
                EntryInput(account=self.a, direction="debit", amount=Decimal("10.00")),
                EntryInput(account=self.b, direction="credit", amount=Decimal("10.00")),
                EntryInput(account=c, direction="debit", amount=Decimal("3.00")),
                EntryInput(account=d, direction="credit", amount=Decimal("3.00")),
            ],
            created_by=self.user,
        )
        post_transaction(transaction=txn, posted_by=self.user)
        self.assertEqual(get_balance(c), Decimal("3.00"))

    def test_per_unit_imbalance_rejected(self):
        unit2 = UnitFactory(ledger=self.ledger, symbol="XU", precision=2)
        c = AccountFactory(ledger=self.ledger, unit=unit2)
        d = AccountFactory(ledger=self.ledger, unit=unit2)
        txn = create_transaction(
            ledger=self.ledger,
            description="cross-bad",
            occurred_at=OCCURRED,
            entries=[
                EntryInput(account=self.a, direction="debit", amount=Decimal("10.00")),
                EntryInput(account=self.b, direction="credit", amount=Decimal("10.00")),
                EntryInput(account=c, direction="debit", amount=Decimal("3.00")),
                EntryInput(account=d, direction="credit", amount=Decimal("4.00")),
            ],
            created_by=self.user,
        )
        with self.assertRaises(ConservationError):
            post_transaction(transaction=txn, posted_by=self.user)

    def test_domain_validator_rejects(self):
        self.b.metadata = {"non_negative": True}
        self.b.save()
        txn = self.draft()
        with self.assertRaises(DomainValidationError):
            post_transaction(transaction=txn, posted_by=self.user)
        self.assertEqual(Transaction.objects.get(pk=txn.pk).status, TransactionStatus.DRAFT)
        self.assertEqual(get_balance(self.b), Decimal(0))

    def test_domain_validator_allows_positive(self):
        self.a.metadata = {"non_negative": True}
        self.a.save()
        post_transaction(transaction=self.draft(), posted_by=self.user)
        self.assertEqual(get_balance(self.a), Decimal("100.00"))


class ReverseTransactionTests(PostingTestBase):
    def test_reverse_restores_balances(self):
        txn = post_transaction(transaction=self.draft(), posted_by=self.user)
        mirror = reverse_transaction(transaction=txn, reversed_by=self.user)
        txn.refresh_from_db()
        self.assertEqual(txn.status, TransactionStatus.REVERSED)
        self.assertEqual(txn.reversed_by_id, mirror.id)
        self.assertEqual(mirror.reverses_id, txn.id)
        self.assertEqual(mirror.status, TransactionStatus.POSTED)
        self.assertEqual(get_balance(self.a), Decimal(0))
        self.assertEqual(get_balance(self.b), Decimal(0))

    def test_reverse_defaults_description(self):
        txn = post_transaction(transaction=self.draft(), posted_by=self.user)
        mirror = reverse_transaction(transaction=txn, reversed_by=self.user)
        self.assertIn("Reversal of", mirror.description)

    def test_reverse_custom_description_and_occurred_at(self):
        txn = post_transaction(transaction=self.draft(), posted_by=self.user)
        custom_time = datetime(2026, 2, 1, tzinfo=UTC)
        mirror = reverse_transaction(
            transaction=txn,
            reversed_by=self.user,
            description="undo",
            occurred_at=custom_time,
        )
        self.assertEqual(mirror.description, "undo")
        self.assertEqual(mirror.occurred_at, custom_time)

    def test_reverse_draft_rejected(self):
        with self.assertRaises(ImmutabilityError):
            reverse_transaction(transaction=self.draft(), reversed_by=self.user)

    def test_double_reverse_rejected(self):
        txn = post_transaction(transaction=self.draft(), posted_by=self.user)
        reverse_transaction(transaction=txn, reversed_by=self.user)
        txn.refresh_from_db()
        with self.assertRaises(ImmutabilityError):
            reverse_transaction(transaction=txn, reversed_by=self.user)

    def test_reversal_of_reversal_reinstates(self):
        txn = post_transaction(transaction=self.draft(), posted_by=self.user)
        mirror = reverse_transaction(transaction=txn, reversed_by=self.user)
        reverse_transaction(transaction=mirror, reversed_by=self.user)
        self.assertEqual(get_balance(self.a), Decimal("100.00"))


class ImmutabilityModelTests(PostingTestBase):
    def test_posted_transaction_field_update_raises(self):
        txn = post_transaction(transaction=self.draft(), posted_by=self.user)
        txn.description = "hacked"
        with self.assertRaises(ImmutabilityError):
            txn.save()

    def test_posted_transaction_delete_raises(self):
        txn = post_transaction(transaction=self.draft(), posted_by=self.user)
        with self.assertRaises(ImmutabilityError):
            txn.delete()

    def test_reversed_transaction_update_raises(self):
        txn = post_transaction(transaction=self.draft(), posted_by=self.user)
        reverse_transaction(transaction=txn, reversed_by=self.user)
        txn.refresh_from_db()
        txn.description = "hacked"
        with self.assertRaises(ImmutabilityError):
            txn.save()

    def test_posted_entry_update_raises(self):
        txn = post_transaction(transaction=self.draft(), posted_by=self.user)
        entry = txn.entries.first()
        entry.amount = Decimal("999.00")
        with self.assertRaises(ImmutabilityError):
            entry.save()

    def test_posted_entry_delete_raises(self):
        txn = post_transaction(transaction=self.draft(), posted_by=self.user)
        entry = txn.entries.first()
        with self.assertRaises(ImmutabilityError):
            entry.delete()

    def test_draft_fully_mutable_and_deletable(self):
        txn = self.draft()
        txn.description = "edited"
        txn.save()
        entry = txn.entries.first()
        entry.amount = Decimal("50.00")
        entry.save()
        entry.delete()
        txn.delete()
        self.assertFalse(Transaction.objects.filter(pk=txn.pk).exists())

    def test_posted_transaction_helper(self):
        txn = posted_transaction(
            ledger=self.ledger,
            debit_account=self.a,
            credit_account=self.b,
            amount=Decimal("42.00"),
            user=self.user,
        )
        self.assertEqual(txn.status, TransactionStatus.POSTED)
        self.assertEqual(get_balance(self.a), Decimal("42.00"))

    def test_balance_row_created_lazily(self):
        self.assertFalse(AccountBalance.objects.filter(account=self.a).exists())
        post_transaction(transaction=self.draft(), posted_by=self.user)
        self.assertTrue(AccountBalance.objects.filter(account=self.a).exists())
