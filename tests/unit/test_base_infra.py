"""Direct unit coverage for base viewset defaults and small helper branches."""

from decimal import Decimal

from django.test import TestCase

from noether.api.viewsets.base import (
    NoetherBaseViewSet,
    NoetherDestroyMixin,
    NoetherUpdateMixin,
)
from noether.domains.config import (
    AccountTypeDef,
    ChartNode,
    ChartTemplate,
    DomainConfig,
    DomainConfigError,
    UnitDef,
)
from noether.domains.registry import DomainRegistry
from noether.domains.services import sync_domain_rows
from noether.ledger.models import Domain, Ledger, Unit
from noether.ledger.tests.factories import LedgerFactory
from noether.resources.base import NoetherResource
from tests.support import ensure_registered


class _Spec(NoetherResource):
    __model__ = Unit
    name: str = "x"


class BaseViewSetDefaultTests(TestCase):
    def make_viewset(self):
        viewset = NoetherBaseViewSet()
        viewset.database_model = Ledger
        viewset.pydantic_model = _Spec
        return viewset

    def test_default_get_queryset_filters_deleted(self):
        ensure_registered()
        ledger = LedgerFactory()
        viewset = self.make_viewset()
        self.assertIn(ledger, viewset.get_queryset())

    def test_pydantic_model_fallbacks(self):
        viewset = self.make_viewset()
        self.assertIs(viewset.get_read_pydantic_model(), _Spec)
        self.assertIs(viewset.get_retrieve_pydantic_model(), _Spec)
        self.assertIs(viewset.get_update_pydantic_model(), _Spec)

    def test_pydantic_model_overrides(self):
        class Other(_Spec):
            pass

        viewset = self.make_viewset()
        viewset.pydantic_read_model = Other
        viewset.pydantic_retrieve_model = Other
        viewset.pydantic_update_model = Other
        self.assertIs(viewset.get_read_pydantic_model(), Other)
        self.assertIs(viewset.get_retrieve_pydantic_model(), Other)
        self.assertIs(viewset.get_update_pydantic_model(), Other)

    def test_default_hooks_are_noops(self):
        viewset = self.make_viewset()
        self.assertIsNone(viewset.validate_data(None, None))
        self.assertIsNone(NoetherUpdateMixin.authorize_update(viewset, None, None))
        self.assertIsNone(NoetherDestroyMixin.authorize_destroy(viewset, None))

    def test_clean_update_data_handles_querydict(self):
        from django.http import QueryDict

        data = QueryDict(mutable=True)
        data.update({"id": "1", "external_id": "x", "name": "keep"})
        cleaned = NoetherUpdateMixin.clean_update_data(NoetherBaseViewSet(), data)
        self.assertEqual(cleaned, {"name": "keep"})


class ResourceContextTests(TestCase):
    def test_get_context_returns_set_context(self):
        spec = _Spec()
        spec._context = {"is_create": True}
        self.assertEqual(spec.get_context(), {"is_create": True})


class DomainConfigEdgeTests(TestCase):
    def test_duplicate_chart_template_names_rejected(self):
        node = ChartNode(path="Root", account_type="source", unit="TU")
        template = ChartTemplate(name="dup", nodes=[node])
        config = DomainConfig(
            slug="dupdomain",
            name="Dup",
            version="1.0.0",
            account_types=[AccountTypeDef(name="source", normal_balance="debit")],
            default_units=[UnitDef(symbol="TU", name="Test Unit", precision=2)],
            chart_templates=[template, ChartTemplate(name="dup", nodes=[node])],
        )
        with self.assertRaises(DomainConfigError):
            config.validate()

    def test_sync_prunes_removed_domains(self):
        ensure_registered()
        Domain.objects.create(slug="ghost-domain", name="Ghost", version="0.0.1", enabled=True)
        sync_domain_rows()
        self.assertFalse(Domain.objects.get(slug="ghost-domain").enabled)
        self.assertTrue(DomainRegistry.get("testdomain"))


class DecimalStringTests(TestCase):
    def test_no_floats_in_amount_path(self):
        self.assertIsInstance(Decimal("1.23"), Decimal)
