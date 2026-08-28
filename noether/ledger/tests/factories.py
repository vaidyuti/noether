from datetime import UTC, datetime
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from noether.ledger.models import (
    Account,
    Domain,
    Entry,
    EntryDirection,
    Ledger,
    Transaction,
    Unit,
)
from noether.ledger.services.posting import post_transaction
from noether.users.models import User


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")


class DomainFactory(DjangoModelFactory):
    class Meta:
        model = Domain
        django_get_or_create = ("slug",)

    slug = "testdomain"
    name = "Test Domain"
    version = "1.0.0"


class LedgerFactory(DjangoModelFactory):
    class Meta:
        model = Ledger

    domain = factory.SubFactory(DomainFactory)
    name = factory.Sequence(lambda n: f"Ledger {n}")


class UnitFactory(DjangoModelFactory):
    class Meta:
        model = Unit

    ledger = factory.SubFactory(LedgerFactory)
    symbol = factory.Sequence(lambda n: f"U{n}")
    name = factory.LazyAttribute(lambda o: f"Unit {o.symbol}")
    precision = 2


class AccountFactory(DjangoModelFactory):
    class Meta:
        model = Account

    ledger = factory.SubFactory(LedgerFactory)
    unit = factory.LazyAttribute(lambda o: UnitFactory(ledger=o.ledger))
    name = factory.Sequence(lambda n: f"Account {n}")
    account_type = "generic"


class TransactionFactory(DjangoModelFactory):
    class Meta:
        model = Transaction

    ledger = factory.SubFactory(LedgerFactory)
    description = factory.Sequence(lambda n: f"Transaction {n}")
    occurred_at = factory.LazyFunction(lambda: datetime.now(UTC))


class EntryFactory(DjangoModelFactory):
    class Meta:
        model = Entry

    transaction = factory.SubFactory(TransactionFactory)
    account = factory.LazyAttribute(lambda o: AccountFactory(ledger=o.transaction.ledger))
    direction = EntryDirection.DEBIT
    amount = Decimal("100.00")


def posted_transaction(*, ledger, debit_account, credit_account, amount, user, **kwargs):
    """Create and post a balanced two-entry transaction."""
    txn = TransactionFactory(ledger=ledger, **kwargs)
    EntryFactory(
        transaction=txn,
        account=debit_account,
        direction=EntryDirection.DEBIT,
        amount=amount,
    )
    EntryFactory(
        transaction=txn,
        account=credit_account,
        direction=EntryDirection.CREDIT,
        amount=amount,
    )
    return post_transaction(transaction=txn, posted_by=user)
