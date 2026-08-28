"""Tests for ADR-0010 (normalized balances) and ADR-0011 (plug hooks)."""

import importlib
from dataclasses import replace
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import clear_url_caches, resolve

from noether.domains.config import DomainConfig, DomainConfigError
from noether.domains.registry import DomainRegistry
from noether.domains.services import create_ledger
from noether.ledger.models import Account, Unit
from noether.ledger.services.balances import get_balance, get_raw_balance, normal_sign
from noether.ledger.services.posting import EntryInput, create_transaction, post_transaction
from noether.ledger.tests.factories import (
    AccountFactory,
    LedgerFactory,
    UnitFactory,
    UserFactory,
    posted_transaction,
)
from noether.security.models import LedgerUser
from tests.support import TEST_DOMAIN, ensure_registered


class NormalSignTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_registered()
        cls.user = UserFactory()
        cls.ledger = LedgerFactory()
        cls.unit = UnitFactory(ledger=cls.ledger, symbol="TU")
        cls.debit = AccountFactory(ledger=cls.ledger, unit=cls.unit, account_type="generic")
        cls.credit = AccountFactory(ledger=cls.ledger, unit=cls.unit, account_type="boundary")

    def test_debit_normal_is_positive(self):
        self.assertEqual(normal_sign(self.debit), 1)

    def test_credit_normal_is_negative(self):
        self.assertEqual(normal_sign(self.credit), -1)

    def test_unknown_account_type_defaults_debit_normal(self):
        account = AccountFactory(ledger=self.ledger, unit=self.unit, account_type="mystery")
        self.assertEqual(normal_sign(account), 1)

    def test_unregistered_domain_defaults_debit_normal(self):
        ledger = LedgerFactory(domain__slug="ghost", domain__name="Ghost")
        unit = UnitFactory(ledger=ledger)
        account = AccountFactory(ledger=ledger, unit=unit, account_type="generic")
        self.assertEqual(normal_sign(account), 1)

    def test_get_balance_normalizes_credit_account(self):
        posted_transaction(
            ledger=self.ledger,
            debit_account=self.debit,
            credit_account=self.credit,
            amount=Decimal("25.00"),
            user=self.user,
        )
        self.assertEqual(get_raw_balance(self.credit), Decimal("-25.00"))
        self.assertEqual(get_balance(self.credit), Decimal("25.00"))
        self.assertEqual(get_raw_balance(self.debit), Decimal("25.00"))
        self.assertEqual(get_balance(self.debit), Decimal("25.00"))


class RecordingValidator:
    def __init__(self):
        self.seen = None

    def validate(self, transaction, entries, balances_after):
        self.seen = balances_after


class ValidatorNormalizationTests(TestCase):
    def test_validator_receives_normalized_balances(self):
        ensure_registered()
        recorder = RecordingValidator()
        config = TEST_DOMAIN
        user = UserFactory()
        ledger = LedgerFactory()
        unit = UnitFactory(ledger=ledger, symbol="TU")
        debit = AccountFactory(ledger=ledger, unit=unit, account_type="generic")
        credit = AccountFactory(ledger=ledger, unit=unit, account_type="boundary")
        config.validators.append(recorder)
        try:
            txn = create_transaction(
                ledger=ledger,
                description="t",
                occurred_at=ledger.created_date,
                entries=[
                    EntryInput(account=debit, direction="debit", amount=Decimal("10.00")),
                    EntryInput(account=credit, direction="credit", amount=Decimal("10.00")),
                ],
                created_by=user,
            )
            post_transaction(transaction=txn, posted_by=user)
        finally:
            config.validators.remove(recorder)
        self.assertEqual(recorder.seen[debit.id], Decimal("10.00"))
        self.assertEqual(recorder.seen[credit.id], Decimal("10.00"))


class CreateLedgerServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_registered()
        call_command("sync_permissions_roles")
        call_command("sync_domains")
        cls.user = UserFactory()

    def test_happy_path_with_chart_and_owner_role(self):
        ledger = create_ledger(
            domain_slug="testdomain",
            name="Svc Ledger",
            owner=self.user,
            chart_template="default",
            description="via service",
        )
        self.assertEqual(ledger.created_by, self.user)
        self.assertEqual(ledger.description, "via service")
        self.assertEqual(Unit.objects.filter(ledger=ledger).count(), 2)
        self.assertTrue(Account.objects.filter(ledger=ledger, name="Main").exists())
        self.assertTrue(
            LedgerUser.objects.filter(ledger=ledger, user=self.user, role__name="Owner").exists()
        )

    def test_no_template(self):
        ledger = create_ledger(domain_slug="testdomain", name="Bare", owner=self.user)
        self.assertEqual(Account.objects.filter(ledger=ledger).count(), 0)

    def test_unknown_domain_raises(self):
        with self.assertRaises(DomainConfigError):
            create_ledger(domain_slug="nope", name="X", owner=self.user)

    def test_unsynced_domain_raises(self):
        config = DomainConfig(slug="unsynced", name="U", version="1.0.0")
        DomainRegistry.register(config)
        try:
            with self.assertRaises(DomainConfigError):
                create_ledger(domain_slug="unsynced", name="X", owner=self.user)
        finally:
            DomainRegistry.unregister("unsynced")

    def test_unknown_template_raises(self):
        with self.assertRaises(DomainConfigError):
            create_ledger(
                domain_slug="testdomain",
                name="X",
                owner=self.user,
                chart_template="nope",
            )


class RegistryIdenticalTests(TestCase):
    def test_equal_but_distinct_config_is_noop(self):
        ensure_registered()
        clone = replace(TEST_DOMAIN)
        DomainRegistry.register(clone)
        self.assertIs(DomainRegistry.get("testdomain"), TEST_DOMAIN)

    def test_different_validator_types_conflict(self):
        ensure_registered()
        clone = replace(TEST_DOMAIN, validators=[RecordingValidator()])
        with self.assertRaises(DomainConfigError):
            DomainRegistry.register(clone)


@override_settings(ROOT_URLCONF="config.urls")
class PlugUrlMountingTests(TestCase):
    def test_plug_urlconf_mounts_under_slug(self):
        config = DomainConfig(
            slug="plugtest",
            name="Plug Test",
            version="1.0.0",
            urls="tests.plug_urls",
        )
        DomainRegistry.register(config)
        try:
            import config.urls as root_urls
            import noether.domains.urls as plug_urls

            importlib.reload(plug_urls)
            importlib.reload(root_urls)
            clear_url_caches()
            match = resolve("/api/v1/plugs/plugtest/ping/")
            self.assertEqual(match.url_name, "plugtest-ping")
            response = self.client.get("/api/v1/plugs/plugtest/ping/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"ok": True})
        finally:
            DomainRegistry.unregister("plugtest")
            importlib.reload(plug_urls)
            importlib.reload(root_urls)
            clear_url_caches()
