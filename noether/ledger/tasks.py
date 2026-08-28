import logging

from celery import shared_task
from django.conf import settings
from django.db import connection
from django.utils import timezone

from noether.ledger.models import Account, AccountBalance, BalanceSnapshot, Ledger, UnitPrice
from noether.ledger.services.balances import _fold_entries, get_raw_balance

logger = logging.getLogger(__name__)

SNAPSHOT_LOCK_KEY = 761201
VERIFY_LOCK_KEY = 761202


def _try_advisory_lock(key: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [key])
        return cursor.fetchone()[0]


def _advisory_unlock(key: int) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", [key])


@shared_task(name="ledger.snapshot_balances")
def snapshot_balances() -> int:
    """Write a BalanceSnapshot per account. Idempotent; advisory-locked."""
    if not _try_advisory_lock(SNAPSHOT_LOCK_KEY):
        return 0
    try:
        now = timezone.now()
        count = 0
        for account in Account.objects.filter(deleted=False, is_placeholder=False):
            BalanceSnapshot.objects.create(
                account=account, as_of=now, balance=get_raw_balance(account)
            )
            count += 1
        return count
    finally:
        _advisory_unlock(SNAPSHOT_LOCK_KEY)


@shared_task(name="ledger.verify_integrity")
def verify_integrity() -> list[str]:
    """Re-derive balances from entries and compare to AccountBalance rows."""
    if not _try_advisory_lock(VERIFY_LOCK_KEY):
        return []
    try:
        drifts = []
        for row in AccountBalance.objects.select_related("account"):
            derived = _fold_entries(row.account, None, None)
            if derived != row.balance:
                drifts.append(
                    f"account {row.account.external_id}: "
                    f"materialized {row.balance} != derived {derived}"
                )
        for drift in drifts:
            logger.error("integrity drift: %s", drift)
        if drifts and settings.INTEGRITY_ALERT_WEBHOOK:
            _post_webhook(drifts)
        return drifts
    finally:
        _advisory_unlock(VERIFY_LOCK_KEY)


def _post_webhook(drifts: list[str]) -> None:
    import requests

    requests.post(settings.INTEGRITY_ALERT_WEBHOOK, json={"drifts": drifts}, timeout=10)


@shared_task(name="domains.fetch_prices")
def fetch_prices(domain_slug: str) -> int:
    """Run the domain's ValuationStrategy for every ledger of that domain."""
    from noether.domains.registry import DomainRegistry

    config = DomainRegistry.get(domain_slug)
    if config.valuation is None:
        return 0
    count = 0
    for ledger in Ledger.objects.filter(domain__slug=domain_slug, deleted=False):
        units = {unit.symbol: unit for unit in ledger.units.all()}
        for quote in config.valuation.fetch_prices(ledger):
            unit = units.get(quote.unit_symbol)
            quote_unit = units.get(quote.quote_unit_symbol)
            if unit is None or quote_unit is None:
                logger.warning(
                    "skipping quote %s/%s for ledger %s: unknown unit",
                    quote.unit_symbol,
                    quote.quote_unit_symbol,
                    ledger.external_id,
                )
                continue
            UnitPrice.objects.create(
                ledger=ledger,
                unit=unit,
                quote_unit=quote_unit,
                price=quote.price,
                as_of=quote.as_of,
                source=quote.source,
            )
            count += 1
    return count
