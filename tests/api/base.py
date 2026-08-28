from datetime import UTC, datetime

from django.core.management import call_command
from rest_framework.test import APITestCase

from noether.ledger.tests.factories import (
    AccountFactory,
    LedgerFactory,
    UnitFactory,
    UserFactory,
)
from noether.security.models import LedgerUser as SecurityLedgerUser
from noether.security.models import Role
from tests.support import ensure_registered

OCCURRED = "2026-01-15T00:00:00Z"
OCCURRED_DT = datetime(2026, 1, 15, tzinfo=UTC)


class NoetherAPITestCase(APITestCase):
    """Common fixture: synced RBAC, testdomain, an owner-membered ledger."""

    @classmethod
    def setUpTestData(cls):
        ensure_registered()
        call_command("sync_permissions_roles")
        call_command("sync_domains")
        cls.owner = UserFactory()
        cls.viewer = UserFactory()
        cls.outsider = UserFactory()
        cls.ledger = LedgerFactory()
        cls.owner_role = Role.objects.get(name="Owner")
        cls.viewer_role = Role.objects.get(name="Viewer")
        SecurityLedgerUser.objects.create(ledger=cls.ledger, user=cls.owner, role=cls.owner_role)
        SecurityLedgerUser.objects.create(ledger=cls.ledger, user=cls.viewer, role=cls.viewer_role)
        cls.unit = UnitFactory(ledger=cls.ledger, symbol="TU", precision=2)
        cls.a = AccountFactory(ledger=cls.ledger, unit=cls.unit, name="A")
        cls.b = AccountFactory(ledger=cls.ledger, unit=cls.unit, name="B")

    def setUp(self):
        self.client.force_authenticate(self.owner)

    def ledger_url(self, suffix=""):
        return f"/api/v1/ledgers/{self.ledger.external_id}/{suffix}"

    def txn_payload(self, amount="100.00", post=False, **extra):
        payload = {
            "description": "test txn",
            "occurred_at": OCCURRED,
            "entries": [
                {"account": str(self.a.external_id), "direction": "debit", "amount": amount},
                {"account": str(self.b.external_id), "direction": "credit", "amount": amount},
            ],
        }
        if post:
            payload["post"] = True
        payload.update(extra)
        return payload

    def create_txn(self, **kwargs):
        response = self.client.post(
            self.ledger_url("transactions/"), self.txn_payload(**kwargs), format="json"
        )
        assert response.status_code == 201, response.content
        return response.json()
