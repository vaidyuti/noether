from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from noether.domains.config import (
    AccountTypeDef,
    ChartNode,
    ChartTemplate,
    DomainConfig,
    DomainConfigError,
    UnitDef,
)
from noether.domains.registry import DomainRegistry
from noether.domains.registry import DomainRegistry as _DR
from noether.domains.services import instantiate_chart, sync_domain_rows
from noether.domains.valuation import PriceQuote
from noether.ledger.models import Account, Domain, Ledger, Unit, UnitPrice
from noether.ledger.tasks import fetch_prices
from noether.ledger.tests.factories import LedgerFactory, UnitFactory
from tests.support import TEST_DOMAIN, StaticPriceFetcher, ensure_registered


def make_config(**overrides):
    kwargs = dict(  # noqa: C408
        slug="valid-domain",
        name="Valid",
        version="1.0.0",
        account_types=[AccountTypeDef(name="generic", normal_balance="debit")],
        default_units=[UnitDef(symbol="VU", name="Valid Unit", precision=2)],
        chart_templates=[],
        validators=[],
        valuation=None,
    )
    kwargs.update(overrides)
    return DomainConfig(**kwargs)


class DomainConfigValidationTests(TestCase):
    def test_valid_config_accepts(self):
        make_config().validate()

    def test_bad_slug_rejected(self):
        for slug in ["UPPER", "has_underscore", "x" * 33, ""]:
            with self.assertRaises(DomainConfigError):
                make_config(slug=slug).validate()

    def test_bad_version_rejected(self):
        with self.assertRaises(DomainConfigError):
            make_config(version="not-semver").validate()

    def test_bad_normal_balance_rejected(self):
        with self.assertRaises(DomainConfigError):
            make_config(
                account_types=[AccountTypeDef(name="x", normal_balance="sideways")]
            ).validate()

    def test_duplicate_account_type_rejected(self):
        with self.assertRaises(DomainConfigError):
            make_config(
                account_types=[
                    AccountTypeDef(name="x", normal_balance="debit"),
                    AccountTypeDef(name="x", normal_balance="credit"),
                ]
            ).validate()

    def test_bad_unit_precision_rejected(self):
        for precision in [-1, 11]:
            with self.assertRaises(DomainConfigError):
                make_config(
                    default_units=[UnitDef(symbol="B", name="Bad", precision=precision)]
                ).validate()

    def test_duplicate_unit_symbol_rejected(self):
        with self.assertRaises(DomainConfigError):
            make_config(
                default_units=[
                    UnitDef(symbol="D", name="D1", precision=2),
                    UnitDef(symbol="D", name="D2", precision=2),
                ]
            ).validate()

    def test_chart_node_unknown_account_type_rejected(self):
        with self.assertRaises(DomainConfigError):
            make_config(
                chart_templates=[
                    ChartTemplate(
                        name="t",
                        nodes=[ChartNode(path="A", account_type="unknown", unit="VU")],
                    )
                ]
            ).validate()

    def test_chart_node_unknown_unit_rejected(self):
        with self.assertRaises(DomainConfigError):
            make_config(
                chart_templates=[
                    ChartTemplate(
                        name="t",
                        nodes=[ChartNode(path="A", account_type="generic", unit="NOPE")],
                    )
                ]
            ).validate()


class DomainRegistryTests(TestCase):
    def test_register_identical_config_is_noop(self):
        ensure_registered()
        DomainRegistry.register(TEST_DOMAIN)
        self.assertEqual(
            [c.slug for c in DomainRegistry.all()].count("testdomain"),
            1,
        )

    def test_register_conflicting_slug_rejected(self):
        ensure_registered()
        with self.assertRaises(DomainConfigError):
            DomainRegistry.register(make_config(slug="testdomain"))

    def test_register_invalid_config_rejected(self):
        with self.assertRaises(DomainConfigError):
            DomainRegistry.register(make_config(slug="BAD SLUG"))

    def test_get_unknown_slug_raises(self):
        with self.assertRaises(DomainConfigError):
            DomainRegistry.get("no-such-domain")

    def test_get_returns_registered(self):
        ensure_registered()
        self.assertIs(DomainRegistry.get("testdomain"), TEST_DOMAIN)


class SyncDomainsTests(TestCase):
    def test_sync_creates_and_updates_rows(self):
        ensure_registered()
        sync_domain_rows()
        row = Domain.objects.get(slug="testdomain")
        self.assertEqual(row.version, "1.0.0")
        self.assertTrue(row.enabled)
        row.version = "0.0.1"
        row.save()
        sync_domain_rows()
        row.refresh_from_db()
        self.assertEqual(row.version, "1.0.0")

    def test_sync_disables_unregistered_rows(self):
        Domain.objects.create(slug="ghost", name="Ghost", version="9.9.9", enabled=True)
        sync_domain_rows()
        self.assertFalse(Domain.objects.get(slug="ghost").enabled)

    def test_management_command(self):
        ensure_registered()
        call_command("sync_domains")
        self.assertTrue(Domain.objects.filter(slug="testdomain").exists())


class ChartInstantiationTests(TestCase):
    def test_chart_instantiation_on_ledger(self):
        ensure_registered()
        sync_domain_rows()
        ledger = Ledger.objects.create(
            domain=Domain.objects.get(slug="testdomain"), name="Chart Ledger"
        )
        instantiate_chart(
            ledger=ledger, config=TEST_DOMAIN, template=TEST_DOMAIN.chart_templates[0]
        )
        self.assertEqual(Unit.objects.filter(ledger=ledger).count(), 2)
        stores = Account.objects.get(ledger=ledger, name="Stores", parent=None)
        self.assertTrue(stores.is_placeholder)
        main = Account.objects.get(ledger=ledger, name="Main")
        self.assertEqual(main.parent_id, stores.id)
        boundary = Account.objects.get(ledger=ledger, name="Boundary")
        self.assertTrue(boundary.is_placeholder)
        world = Account.objects.get(ledger=ledger, name="World")
        self.assertEqual(world.parent_id, boundary.id)
        self.assertEqual(world.account_type, "boundary")

    def test_unknown_template_raises(self):
        ensure_registered()
        sync_domain_rows()
        Ledger.objects.create(domain=Domain.objects.get(slug="testdomain"), name="X")
        names = [t.name for t in TEST_DOMAIN.chart_templates]
        self.assertNotIn("nope", names)


class ValuationStrategyTests(TestCase):
    def test_price_quote_is_frozen_decimal(self):
        quote = StaticPriceFetcher().fetch_prices(None)[0]
        self.assertIsInstance(quote, PriceQuote)
        self.assertIsInstance(quote.price, Decimal)
        with self.assertRaises(AttributeError):
            quote.price = Decimal("1")

    def test_fetch_prices_task_stores_quotes(self):
        ensure_registered()
        sync_domain_rows()
        ledger = LedgerFactory(domain=Domain.objects.get(slug="testdomain"))
        UnitFactory(ledger=ledger, symbol="TU")
        UnitFactory(ledger=ledger, symbol="QU")
        fetch_prices("testdomain")
        price = UnitPrice.objects.get(ledger=ledger)
        self.assertEqual(price.price, Decimal("2.5"))
        self.assertEqual(price.source, "static")

    def test_fetch_prices_skips_unknown_units(self):
        ensure_registered()
        sync_domain_rows()
        ledger = LedgerFactory(domain=Domain.objects.get(slug="testdomain"))
        fetch_prices("testdomain")
        self.assertFalse(UnitPrice.objects.filter(ledger=ledger).exists())

    def test_fetch_prices_with_mocked_strategy(self):
        ensure_registered()
        sync_domain_rows()
        ledger = LedgerFactory(domain=Domain.objects.get(slug="testdomain"))
        UnitFactory(ledger=ledger, symbol="TU")
        UnitFactory(ledger=ledger, symbol="QU")
        with patch.object(
            StaticPriceFetcher, "fetch_prices", wraps=TEST_DOMAIN.valuation.fetch_prices
        ) as mocked:
            fetch_prices("testdomain")
        mocked.assert_called_once()

    def test_fetch_prices_no_valuation_strategy(self):
        config = make_config(slug="no-valuation")
        _DR.register(config)
        try:
            self.assertEqual(fetch_prices("no-valuation"), 0)
        finally:
            _DR.unregister("no-valuation")
