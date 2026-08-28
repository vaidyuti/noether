"""Remaining branch coverage: chart prefix reuse, float price coercion, bad filters."""

from noether.domains.config import (
    AccountTypeDef,
    ChartNode,
    ChartTemplate,
    DomainConfig,
    UnitDef,
)
from noether.domains.registry import DomainRegistry
from noether.domains.services import instantiate_chart
from noether.ledger.models import Account
from noether.ledger.resources.price.spec import UnitPriceSpec
from noether.ledger.tests.factories import LedgerFactory
from tests.api.base import NoetherAPITestCase


class ChartPrefixReuseTests(NoetherAPITestCase):
    def test_node_path_already_created_as_prefix(self):
        config = DomainConfig(
            slug="chartdup",
            name="Chart Dup",
            version="1.0.0",
            account_types=[AccountTypeDef(name="generic", normal_balance="debit")],
            default_units=[UnitDef(symbol="CU", name="Chart Unit", precision=2)],
            chart_templates=[
                ChartTemplate(
                    name="default",
                    nodes=[
                        # child first: creates "Top" as a placeholder prefix,
                        # then the explicit "Top" node hits the already-created branch
                        ChartNode(path="Top/Child", account_type="generic", unit="CU"),
                        ChartNode(path="Top", account_type="generic", unit="CU"),
                    ],
                )
            ],
        )
        DomainRegistry.register(config)
        try:
            ledger = LedgerFactory()
            instantiate_chart(ledger=ledger, config=config, template=config.chart_templates[0])
            self.assertEqual(
                Account.objects.filter(ledger=ledger, name__in=["Top", "Child"]).count(), 2
            )
        finally:
            DomainRegistry.unregister("chartdup")


class PriceFloatCoercionTests(NoetherAPITestCase):
    def test_float_price_coerced_via_validator(self):
        spec = UnitPriceSpec.model_validate(
            {
                "unit": "TU",
                "quote_unit": "QU",
                "price": 1.5,
                "as_of": "2026-01-15T00:00:00Z",
            }
        )
        self.assertEqual(str(spec.price), "1.5")


class TransactionFilterEdgeTests(NoetherAPITestCase):
    def test_invalid_occurred_before_filter_400(self):
        response = self.client.get(self.ledger_url("transactions/") + "?occurred_before=not-a-date")
        self.assertEqual(response.status_code, 400)

    def test_invalid_account_uuid_filter_400(self):
        response = self.client.get(self.ledger_url("transactions/") + "?account=not-a-uuid")
        self.assertEqual(response.status_code, 400)

    def test_invalid_archived_boolean_filter_ignored(self):
        # django-filter's BooleanFilter coerces unrecognized values to None,
        # so an invalid `archived` value is ignored rather than rejected.
        response = self.client.get(self.ledger_url("accounts/") + "?archived=maybe")
        self.assertEqual(response.status_code, 200)

    def test_invalid_parent_uuid_filter_400(self):
        response = self.client.get(self.ledger_url("accounts/") + "?parent=nope")
        self.assertEqual(response.status_code, 400)

    def test_invalid_as_of_before_filter_400(self):
        response = self.client.get(self.ledger_url("prices/") + "?as_of_before=not-a-date")
        self.assertEqual(response.status_code, 400)
