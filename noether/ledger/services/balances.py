from datetime import datetime
from decimal import Decimal

from noether.ledger.models import (
    Account,
    AccountBalance,
    BalanceSnapshot,
    Entry,
    EntryDirection,
    TransactionStatus,
    Unit,
    UnitPrice,
)


class ValuationUnavailableError(Exception):
    """No price is known for the requested unit pair."""


def _fold_entries(account: Account, since: datetime | None, until: datetime | None) -> Decimal:
    entries = Entry.objects.filter(
        account=account,
        transaction__status__in=[TransactionStatus.POSTED, TransactionStatus.REVERSED],
    )
    if since is not None:
        entries = entries.filter(transaction__occurred_at__gt=since)
    if until is not None:
        entries = entries.filter(transaction__occurred_at__lte=until)
    total = Decimal(0)
    for entry in entries:
        if entry.direction == EntryDirection.DEBIT:
            total += entry.amount
        else:
            total -= entry.amount
    return total


def get_balance(account: Account, as_of: datetime | None = None) -> Decimal:
    """Current balance from AccountBalance; point-in-time via snapshot + replay."""
    if as_of is None:
        row = AccountBalance.objects.filter(account=account).first()
        if row is None:
            return Decimal(0)
        return row.balance
    snapshot = (
        BalanceSnapshot.objects.filter(account=account, as_of__lte=as_of)
        .order_by("-as_of")
        .first()
    )
    if snapshot is None:
        return _fold_entries(account, None, as_of)
    return snapshot.balance + _fold_entries(account, snapshot.as_of, as_of)


def get_market_value(account: Account, value_in: Unit, as_of: datetime | None = None) -> Decimal:
    """balance x latest price(unit -> value_in, as_of <= t)."""
    balance = get_balance(account, as_of=as_of)
    if account.unit_id == value_in.id:
        return balance
    prices = UnitPrice.objects.filter(
        ledger=account.ledger, unit=account.unit, quote_unit=value_in
    )
    if as_of is not None:
        prices = prices.filter(as_of__lte=as_of)
    latest = prices.order_by("-as_of").first()
    if latest is None:
        raise ValuationUnavailableError(
            f"no price for {account.unit.symbol} in {value_in.symbol}"
        )
    return balance * latest.price
