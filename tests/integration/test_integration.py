"""Integration tier: real Postgres + Redis, no mocks."""

import threading
from datetime import UTC, datetime
from decimal import Decimal

from django.core.management import call_command
from django.db import connections
from django.test import TransactionTestCase
from rest_framework.test import APIClient

from noether.ledger.models import BalanceSnapshot, Transaction
from noether.ledger.services.balances import get_balance
from noether.ledger.services.posting import EntryInput, create_transaction, post_transaction
from noether.ledger.tasks import snapshot_balances, verify_integrity
from noether.ledger.tests.factories import (
    AccountFactory,
    LedgerFactory,
    UnitFactory,
    UserFactory,
    posted_transaction,
)
from noether.security.models import LedgerUser, Role
from tests.support import ensure_registered

OCCURRED = datetime(2026, 1, 15, tzinfo=UTC)


class ConcurrentPostingTests(TransactionTestCase):
    """Two simultaneous posts against the same accounts must serialize."""

    def setUp(self):
        ensure_registered()
        self.user = UserFactory()
        self.ledger = LedgerFactory()
        self.unit = UnitFactory(ledger=self.ledger, symbol="TU", precision=2)
        self.a = AccountFactory(ledger=self.ledger, unit=self.unit)
        self.b = AccountFactory(ledger=self.ledger, unit=self.unit)

    def test_concurrent_posts_serialize_correctly(self):
        drafts = []
        for _ in range(2):
            drafts.append(
                create_transaction(
                    ledger=self.ledger,
                    description="concurrent",
                    occurred_at=OCCURRED,
                    entries=[
                        EntryInput(account=self.a, direction="debit", amount=Decimal("10.00")),
                        EntryInput(account=self.b, direction="credit", amount=Decimal("10.00")),
                    ],
                    created_by=self.user,
                )
            )
        barrier = threading.Barrier(2)
        errors = []

        def worker(txn):
            try:
                barrier.wait(timeout=10)
                post_transaction(transaction=txn, posted_by=self.user)
            except Exception as exc:  # noqa: BLE001 — collected and asserted below
                errors.append(exc)
            finally:
                for conn in connections.all():
                    conn.close()

        threads = [threading.Thread(target=worker, args=(txn,)) for txn in drafts]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertEqual(get_balance(self.a), Decimal("20.00"))
        self.assertEqual(get_balance(self.b), Decimal("-20.00"))


class CeleryTaskTests(TransactionTestCase):
    def setUp(self):
        ensure_registered()
        self.user = UserFactory()
        self.ledger = LedgerFactory()
        self.unit = UnitFactory(ledger=self.ledger, symbol="TU", precision=2)
        self.a = AccountFactory(ledger=self.ledger, unit=self.unit)
        self.b = AccountFactory(ledger=self.ledger, unit=self.unit)
        posted_transaction(
            ledger=self.ledger,
            debit_account=self.a,
            credit_account=self.b,
            amount=Decimal("50.00"),
            user=self.user,
            occurred_at=OCCURRED,
        )

    def test_snapshot_task_end_to_end(self):
        count = snapshot_balances.apply().get()
        self.assertEqual(count, 2)
        snapshot = BalanceSnapshot.objects.get(account=self.a)
        self.assertEqual(snapshot.balance, Decimal("50.00"))
        # idempotent second run adds another snapshot without corruption
        self.assertEqual(snapshot_balances.apply().get(), 2)

    def test_verifier_clean_state(self):
        self.assertEqual(verify_integrity.apply().get(), [])

    def test_verifier_detects_drift(self):
        from noether.ledger.models import AccountBalance

        AccountBalance.objects.filter(account=self.a).update(balance=Decimal("999"))
        drifts = verify_integrity.apply().get()
        self.assertEqual(len(drifts), 1)
        self.assertIn(str(self.a.external_id), drifts[0])


class JWTFlowTests(TransactionTestCase):
    def setUp(self):
        ensure_registered()
        call_command("sync_permissions_roles")
        call_command("sync_domains")
        self.user = UserFactory(username="jwt-user")
        self.user.set_password("s3cret-pass")
        self.user.save()
        self.ledger = LedgerFactory()
        LedgerUser.objects.create(
            ledger=self.ledger, user=self.user, role=Role.objects.get(name="Owner")
        )
        self.unit = UnitFactory(ledger=self.ledger, symbol="TU", precision=2)
        self.a = AccountFactory(ledger=self.ledger, unit=self.unit)
        self.b = AccountFactory(ledger=self.ledger, unit=self.unit)

    def test_full_jwt_flow(self):
        client = APIClient()
        # bad credentials
        response = client.post(
            "/api/v1/auth/token/",
            {"username": "jwt-user", "password": "wrong"},
            format="json",
        )
        self.assertEqual(response.status_code, 401)
        # obtain
        response = client.post(
            "/api/v1/auth/token/",
            {"username": "jwt-user", "password": "s3cret-pass"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        tokens = response.json()
        # refresh
        response = client.post(
            "/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        access = response.json()["access"]
        # authenticated call posts a transaction over HTTP
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = client.post(
            f"/api/v1/ledgers/{self.ledger.external_id}/transactions/",
            {
                "description": "jwt txn",
                "occurred_at": "2026-01-15T00:00:00Z",
                "post": True,
                "entries": [
                    {"account": str(self.a.external_id), "direction": "debit", "amount": "5.00"},
                    {"account": str(self.b.external_id), "direction": "credit", "amount": "5.00"},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            Transaction.objects.get(external_id=response.json()["id"]).status, "posted"
        )
