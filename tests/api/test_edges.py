"""Coverage-gap tests: exception handler branches, mixin defaults, task locks, API edges."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from django.test import TestCase, override_settings
from rest_framework.exceptions import ValidationError as DRFValidationError

from noether.api.viewsets.base import noether_exception_handler
from noether.domains.validators import TransactionValidator
from noether.domains.valuation import ValuationStrategy
from noether.ledger.tasks import snapshot_balances, verify_integrity
from noether.ledger.tests.factories import (
    AccountFactory,
    LedgerFactory,
    UnitFactory,
    UserFactory,
    posted_transaction,
)
from tests.api.base import NoetherAPITestCase
from tests.support import ensure_registered

OCCURRED = "2026-01-15T00:00:00Z"


class ExceptionHandlerTests(TestCase):
    def test_django_validation_error_translated(self):
        response = noether_exception_handler(DjangoValidationError("bad value"), {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"][0]["type"], "validation_error")

    def test_drf_error_with_errors_dict_passthrough(self):
        exc = DRFValidationError(detail={"errors": [{"type": "x", "msg": "y"}]})
        response = noether_exception_handler(exc, {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["errors"][0]["type"], "x")

    def test_drf_error_with_plain_dict(self):
        exc = DRFValidationError(detail={"field": "broken"})
        response = noether_exception_handler(exc, {})
        self.assertEqual(response.status_code, 400)
        self.assertIn("broken", response.data["errors"][0]["msg"])

    def test_http404_without_args(self):
        response = noether_exception_handler(Http404(), {})
        self.assertEqual(response.data["errors"][0]["msg"], "Object not found")

    def test_unhandled_exception_falls_through(self):
        self.assertIsNone(noether_exception_handler(RuntimeError("boom"), {"view": None}))


class AbstractContractTests(TestCase):
    def test_transaction_validator_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            TransactionValidator().validate(None, [], {})

    def test_valuation_strategy_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            ValuationStrategy().fetch_prices(None)


class TaskLockAndWebhookTests(TestCase):
    def setUp(self):
        ensure_registered()
        self.user = UserFactory()
        self.ledger = LedgerFactory()
        self.unit = UnitFactory(ledger=self.ledger, symbol="TU", precision=2)
        self.a = AccountFactory(ledger=self.ledger, unit=self.unit)
        self.b = AccountFactory(ledger=self.ledger, unit=self.unit)

    def test_snapshot_skips_when_lock_held(self):
        with mock.patch("noether.ledger.tasks._try_advisory_lock", return_value=False):
            self.assertEqual(snapshot_balances.apply().get(), 0)

    def test_verify_skips_when_lock_held(self):
        with mock.patch("noether.ledger.tasks._try_advisory_lock", return_value=False):
            self.assertEqual(verify_integrity.apply().get(), [])

    @override_settings(INTEGRITY_ALERT_WEBHOOK="https://hooks.example/alert")
    def test_verify_posts_webhook_on_drift(self):
        from noether.ledger.models import AccountBalance

        posted_transaction(
            ledger=self.ledger,
            debit_account=self.a,
            credit_account=self.b,
            amount=Decimal("5.00"),
            user=self.user,
            occurred_at=datetime(2026, 1, 15, tzinfo=UTC),
        )
        AccountBalance.objects.filter(account=self.a).update(balance=Decimal("1"))
        with mock.patch("requests.post") as post:
            drifts = verify_integrity.apply().get()
        self.assertEqual(len(drifts), 1)
        post.assert_called_once()


class ApiEdgeTests(NoetherAPITestCase):
    def test_account_unknown_unit_400(self):
        response = self.client.post(
            self.ledger_url("accounts/"),
            {
                "name": "X",
                "account_type": "generic",
                "unit": "11111111-1111-4111-8111-111111111111",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_account_unknown_parent_400(self):
        response = self.client.post(
            self.ledger_url("accounts/"),
            {
                "name": "X",
                "account_type": "generic",
                "unit": str(self.unit.external_id),
                "parent": "11111111-1111-4111-8111-111111111111",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_entry_float_amount_coerced(self):
        response = self.client.post(
            self.ledger_url("transactions/"),
            {
                "description": "float amt",
                "occurred_at": OCCURRED,
                "entries": [
                    {"account": str(self.a.external_id), "direction": "debit", "amount": 5.0},
                    {"account": str(self.b.external_id), "direction": "credit", "amount": 5.0},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_transaction_unknown_account_400(self):
        response = self.client.post(
            self.ledger_url("transactions/"),
            {
                "description": "bad acct",
                "occurred_at": OCCURRED,
                "entries": [
                    {
                        "account": "11111111-1111-4111-8111-111111111111",
                        "direction": "debit",
                        "amount": "5.00",
                    },
                    {"account": str(self.b.external_id), "direction": "credit", "amount": "5.00"},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_transaction_invalid_occurred_at_400(self):
        response = self.client.post(
            self.ledger_url("transactions/"),
            {
                "description": "bad time",
                "occurred_at": "not-a-datetime",
                "entries": [
                    {"account": str(self.a.external_id), "direction": "debit", "amount": "5.00"},
                    {"account": str(self.b.external_id), "direction": "credit", "amount": "5.00"},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_ledger_create_unregistered_domain_400(self):
        response = self.client.post(
            "/api/v1/ledgers/",
            {"name": "L2", "domain": "never-synced"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_ledger_create_registered_but_unsynced_domain_400(self):
        from noether.domains.config import DomainConfig
        from noether.domains.registry import DomainRegistry

        config = DomainConfig(slug="unsynced", name="Unsynced", version="1.0.0")
        DomainRegistry.register(config)
        try:
            response = self.client.post(
                "/api/v1/ledgers/",
                {"name": "L2", "domain": "unsynced"},
                format="json",
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("not synced", response.json()["errors"][0]["msg"])
        finally:
            DomainRegistry.unregister("unsynced")

    def test_member_duplicate_400(self):
        other = UserFactory(username="dupe-member")
        payload = {"user": other.username, "role": "Viewer"}
        response = self.client.post(self.ledger_url("members/"), payload, format="json")
        self.assertEqual(response.status_code, 201)
        response = self.client.post(self.ledger_url("members/"), payload, format="json")
        self.assertEqual(response.status_code, 400)

    def test_member_retrieve(self):
        response = self.client.get(self.ledger_url("members/"))
        member_id = response.json()["results"][0]["id"]
        response = self.client.get(self.ledger_url(f"members/{member_id}/"))
        self.assertEqual(response.status_code, 200)

    def test_price_create_and_retrieve(self):
        quote = UnitFactory(ledger=self.ledger, symbol="QU", precision=2)
        response = self.client.post(
            self.ledger_url("prices/"),
            {
                "unit": self.unit.symbol,
                "quote_unit": quote.symbol,
                "price": "1.5",
                "as_of": OCCURRED,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        price_id = response.json()["id"]
        response = self.client.get(self.ledger_url(f"prices/{price_id}/"))
        self.assertEqual(response.status_code, 200)

    def test_price_nonpositive_400(self):
        quote = UnitFactory(ledger=self.ledger, symbol="QV", precision=2)
        response = self.client.post(
            self.ledger_url("prices/"),
            {
                "unit": self.unit.symbol,
                "quote_unit": quote.symbol,
                "price": "0",
                "as_of": OCCURRED,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_unit_update_same_precision_ok(self):
        response = self.client.patch(
            self.ledger_url(f"units/{self.unit.external_id}/"),
            {"name": "renamed", "symbol": self.unit.symbol, "precision": self.unit.precision},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_unit_retrieve(self):
        response = self.client.get(self.ledger_url(f"units/{self.unit.external_id}/"))
        self.assertEqual(response.status_code, 200)

    def test_account_retrieve(self):
        response = self.client.get(self.ledger_url(f"accounts/{self.a.external_id}/"))
        self.assertEqual(response.status_code, 200)
