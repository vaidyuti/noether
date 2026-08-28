from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone

from noether.domains.registry import DomainRegistry
from noether.ledger.exceptions import ConservationError, ImmutabilityError
from noether.ledger.models import (
    Account,
    AccountBalance,
    Entry,
    EntryDirection,
    Ledger,
    Transaction,
    TransactionStatus,
    Unit,
)


@dataclass(frozen=True)
class EntryInput:
    account: Account
    direction: str
    amount: Decimal
    metadata: dict | None = None


def _validate_entry_account(*, ledger: Ledger, account: Account) -> None:
    if account.ledger_id != ledger.id:
        raise ConservationError(f"account {account.name} does not belong to ledger {ledger.name}")
    if account.is_placeholder:
        raise ConservationError(f"account {account.name} is a placeholder")


def _validate_precision(*, account: Account, amount: Decimal) -> None:
    quantum = Decimal(1).scaleb(-account.unit.precision)
    if amount != amount.quantize(quantum):
        raise ConservationError(
            f"amount {amount} violates precision {account.unit.precision} "
            f"of unit {account.unit.symbol}"
        )


def create_transaction(
    *,
    ledger: Ledger,
    description: str,
    occurred_at: datetime,
    entries: list[EntryInput],
    metadata: dict | None = None,
    created_by,
) -> Transaction:
    """Create a DRAFT transaction with its entries. Kernel-validates cheaply."""
    with db_transaction.atomic():
        txn = Transaction.objects.create(
            ledger=ledger,
            description=description,
            occurred_at=occurred_at,
            metadata=metadata or {},
            created_by=created_by,
            updated_by=created_by,
        )
        for entry_input in entries:
            account = entry_input.account
            amount = Decimal(entry_input.amount)
            _validate_entry_account(ledger=ledger, account=account)
            if amount <= 0:
                raise ConservationError(f"entry amount must be > 0, got {amount}")
            _validate_precision(account=account, amount=amount)
            Entry.objects.create(
                transaction=txn,
                account=account,
                direction=entry_input.direction,
                amount=amount,
                metadata=entry_input.metadata or {},
                created_by=created_by,
                updated_by=created_by,
            )
    return txn


def _check_conservation(entries: list[Entry]) -> None:
    sums: dict[int, dict[str, Decimal]] = {}
    units: dict[int, Unit] = {}
    for entry in entries:
        unit = entry.account.unit
        units[unit.id] = unit
        per_unit = sums.setdefault(unit.id, {"debit": Decimal(0), "credit": Decimal(0)})
        per_unit[entry.direction] += entry.amount
    for unit_id, per_unit in sums.items():
        if per_unit["debit"] != per_unit["credit"]:
            unit = units[unit_id]
            quantum = Decimal(1).scaleb(-unit.precision)
            debits = per_unit["debit"].quantize(quantum)
            credits = per_unit["credit"].quantize(quantum)
            raise ConservationError(f"unit {unit.symbol}: debits {debits} != credits {credits}")


def _signed_delta(entry: Entry) -> Decimal:
    if entry.direction == EntryDirection.DEBIT:
        return entry.amount
    return -entry.amount


def post_transaction(*, transaction: Transaction, posted_by) -> Transaction:
    """Atomic. Runs kernel invariants then domain validators."""
    with db_transaction.atomic():
        txn = Transaction.objects.select_for_update().get(pk=transaction.pk)
        if txn.status != TransactionStatus.DRAFT:
            raise ImmutabilityError(f"transaction {txn.external_id} is already {txn.status}")
        entries = list(
            txn.entries.select_related("account", "account__unit").order_by("account_id")
        )
        if len(entries) < 2:
            raise ConservationError("a postable transaction requires at least 2 entries")
        for entry in entries:
            _validate_entry_account(ledger=txn.ledger, account=entry.account)
            if entry.account.archived:
                raise ConservationError(f"account {entry.account.name} is archived")
            if entry.amount <= 0:
                raise ConservationError(f"entry amount must be > 0, got {entry.amount}")
            _validate_precision(account=entry.account, amount=entry.amount)
        _check_conservation(entries)

        account_ids = sorted({entry.account_id for entry in entries})
        for account_id in account_ids:
            AccountBalance.objects.get_or_create(
                account_id=account_id, defaults={"balance": Decimal(0)}
            )
        balance_rows = {
            row.account_id: row
            for row in AccountBalance.objects.select_for_update()
            .filter(account_id__in=account_ids)
            .order_by("account_id")
        }
        balances_after: dict[int, Decimal] = {
            account_id: balance_rows[account_id].balance for account_id in account_ids
        }
        for entry in entries:
            balances_after[entry.account_id] += _signed_delta(entry)

        config = DomainRegistry.get(txn.ledger.domain.slug)
        for validator in config.validators:
            validator.validate(txn, entries, dict(balances_after))

        for account_id in account_ids:
            row = balance_rows[account_id]
            row.balance = balances_after[account_id]
            row.save(update_fields=["balance", "modified_date"])

        txn.status = TransactionStatus.POSTED
        txn.posted_at = timezone.now()
        txn.updated_by = posted_by
        txn.save()
    return txn


def reverse_transaction(
    *,
    transaction: Transaction,
    reversed_by,
    description: str | None = None,
    occurred_at: datetime | None = None,
) -> Transaction:
    """Create and post the mirror transaction atomically."""
    with db_transaction.atomic():
        txn = Transaction.objects.select_for_update().get(pk=transaction.pk)
        if txn.status != TransactionStatus.POSTED:
            raise ImmutabilityError(
                f"only posted transactions can be reversed; {txn.external_id} is {txn.status}"
            )
        mirror_entries = [
            EntryInput(
                account=entry.account,
                direction=_mirror(entry.direction),
                amount=entry.amount,
                metadata=entry.metadata,
            )
            for entry in txn.entries.select_related("account").order_by("account_id")
        ]
        mirror = create_transaction(
            ledger=txn.ledger,
            description=description
            if description is not None
            else f"Reversal of: {txn.description}",
            occurred_at=occurred_at if occurred_at is not None else timezone.now(),
            entries=mirror_entries,
            metadata={},
            created_by=reversed_by,
        )
        mirror.reverses = txn
        mirror.save()
        mirror = post_transaction(transaction=mirror, posted_by=reversed_by)
        txn.reversed_by = mirror
        txn.status = TransactionStatus.REVERSED
        txn.updated_by = reversed_by
        txn.save()
    return mirror


def _mirror(direction: str) -> str:
    if direction == EntryDirection.DEBIT:
        return EntryDirection.CREDIT
    return EntryDirection.DEBIT
