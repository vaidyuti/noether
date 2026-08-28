from decimal import Decimal

from noether.ledger.models import UnitPrice
from noether.ledger.tests.factories import AccountFactory, UnitFactory
from tests.api.base import NoetherAPITestCase


class UnitAPITests(NoetherAPITestCase):
    def test_list_units(self):
        response = self.client.get(self.ledger_url("units/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["symbol"], "TU")

    def test_create_unit(self):
        response = self.client.post(
            self.ledger_url("units/"),
            {"symbol": "NU", "name": "New Unit", "precision": 3},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["precision"], 3)

    def test_create_duplicate_symbol_400(self):
        response = self.client.post(
            self.ledger_url("units/"),
            {"symbol": "TU", "name": "Dup", "precision": 2},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_precision_out_of_range_400(self):
        response = self.client.post(
            self.ledger_url("units/"),
            {"symbol": "PX", "name": "P", "precision": 11},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_update_unit_name(self):
        response = self.client.patch(
            self.ledger_url(f"units/{self.unit.external_id}/"),
            {"name": "Renamed Unit"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Renamed Unit")

    def test_precision_mutable_while_unused(self):
        unused = UnitFactory(ledger=self.ledger, symbol="UN", precision=2)
        response = self.client.patch(
            self.ledger_url(f"units/{unused.external_id}/"),
            {"precision": 4},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["precision"], 4)

    def test_precision_immutable_once_used_400(self):
        self.create_txn(post=True)
        response = self.client.patch(
            self.ledger_url(f"units/{self.unit.external_id}/"),
            {"precision": 5},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_viewer_cannot_create_403(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.post(
            self.ledger_url("units/"),
            {"symbol": "VX", "name": "V", "precision": 0},
            format="json",
        )
        self.assertEqual(response.status_code, 403)


class AccountAPITests(NoetherAPITestCase):
    def test_list_accounts(self):
        response = self.client.get(self.ledger_url("accounts/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 2)

    def test_filters(self):
        parent = AccountFactory(
            ledger=self.ledger, unit=self.unit, is_placeholder=True, name="P"
        )
        AccountFactory(
            ledger=self.ledger, unit=self.unit, parent=parent, name="C", account_type="boundary"
        )
        r = self.client.get(self.ledger_url(f"accounts/?parent={parent.external_id}"))
        self.assertEqual(len(r.json()["results"]), 1)
        r = self.client.get(self.ledger_url("accounts/?type=boundary"))
        self.assertEqual(len(r.json()["results"]), 1)
        r = self.client.get(self.ledger_url("accounts/?archived=true"))
        self.assertEqual(len(r.json()["results"]), 0)
        r = self.client.get(self.ledger_url("accounts/?archived=false"))
        self.assertEqual(len(r.json()["results"]), 4)

    def test_create_account(self):
        response = self.client.post(
            self.ledger_url("accounts/"),
            {"name": "New", "account_type": "generic", "unit": str(self.unit.external_id)},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["name"], "New")

    def test_create_child_account(self):
        response = self.client.post(
            self.ledger_url("accounts/"),
            {
                "name": "Child",
                "account_type": "generic",
                "unit": str(self.unit.external_id),
                "parent": str(self.a.external_id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["parent"], str(self.a.external_id))

    def test_create_unknown_account_type_400(self):
        response = self.client.post(
            self.ledger_url("accounts/"),
            {"name": "X", "account_type": "nope", "unit": str(self.unit.external_id)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_create_unknown_unit_400(self):
        response = self.client.post(
            self.ledger_url("accounts/"),
            {
                "name": "X",
                "account_type": "generic",
                "unit": "00000000-0000-0000-0000-000000000000",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_create_unknown_parent_400(self):
        response = self.client.post(
            self.ledger_url("accounts/"),
            {
                "name": "X",
                "account_type": "generic",
                "unit": str(self.unit.external_id),
                "parent": "00000000-0000-0000-0000-000000000000",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_update_account(self):
        response = self.client.patch(
            self.ledger_url(f"accounts/{self.a.external_id}/"),
            {"name": "Renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Renamed")

    def test_archive_action(self):
        response = self.client.post(self.ledger_url(f"accounts/{self.a.external_id}/archive/"))
        self.assertEqual(response.status_code, 200)
        self.a.refresh_from_db()
        self.assertTrue(self.a.archived)

    def test_balance_endpoint(self):
        self.create_txn(post=True)
        response = self.client.get(self.ledger_url(f"accounts/{self.a.external_id}/balance/"))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["balance"], "100.00")
        self.assertEqual(body["unit"], "TU")

    def test_balance_as_of(self):
        self.create_txn(post=True)
        response = self.client.get(
            self.ledger_url(
                f"accounts/{self.a.external_id}/balance/?as_of=2026-01-01T00:00:00Z"
            )
        )
        self.assertEqual(response.json()["balance"], "0.00")

    def test_balance_bad_as_of_400(self):
        response = self.client.get(
            self.ledger_url(f"accounts/{self.a.external_id}/balance/?as_of=banana")
        )
        self.assertEqual(response.status_code, 400)

    def test_balance_value_in(self):
        quote = UnitFactory(ledger=self.ledger, symbol="QU", precision=2)
        UnitPrice.objects.create(
            ledger=self.ledger,
            unit=self.unit,
            quote_unit=quote,
            price=Decimal("2.0000000000"),
            as_of="2026-01-01T00:00:00Z",
            source="test",
        )
        self.create_txn(post=True)
        response = self.client.get(
            self.ledger_url(f"accounts/{self.a.external_id}/balance/?value_in=QU")
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["value"], "200.00")
        self.assertEqual(body["value_unit"], "QU")

    def test_balance_value_in_unknown_unit_400(self):
        response = self.client.get(
            self.ledger_url(f"accounts/{self.a.external_id}/balance/?value_in=ZZ")
        )
        self.assertEqual(response.status_code, 400)

    def test_balance_value_in_no_price_400(self):
        UnitFactory(ledger=self.ledger, symbol="QU", precision=2)
        self.create_txn(post=True)
        response = self.client.get(
            self.ledger_url(f"accounts/{self.a.external_id}/balance/?value_in=QU")
        )
        self.assertEqual(response.status_code, 400)

    def test_entries_endpoint(self):
        self.create_txn(post=True)
        response = self.client.get(self.ledger_url(f"accounts/{self.a.external_id}/entries/"))
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["direction"], "debit")
        self.assertEqual(results[0]["amount"], "100.0000000000")

    def test_viewer_can_read_balance(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.get(self.ledger_url(f"accounts/{self.a.external_id}/balance/"))
        self.assertEqual(response.status_code, 200)

    def test_viewer_cannot_read_entries_403(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.get(self.ledger_url(f"accounts/{self.a.external_id}/entries/"))
        self.assertEqual(response.status_code, 403)

    def test_viewer_cannot_archive_403(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.post(self.ledger_url(f"accounts/{self.a.external_id}/archive/"))
        self.assertEqual(response.status_code, 403)


class PriceAPITests(NoetherAPITestCase):
    def setUp(self):
        super().setUp()
        self.quote = UnitFactory(ledger=self.ledger, symbol="QU", precision=2)

    def price_payload(self, **extra):
        payload = {
            "unit": "TU",
            "quote_unit": "QU",
            "price": "2.5",
            "as_of": "2026-01-01T00:00:00Z",
            "source": "manual",
        }
        payload.update(extra)
        return payload

    def test_create_price(self):
        response = self.client.post(
            self.ledger_url("prices/"), self.price_payload(), format="json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["price"], "2.5000000000")

    def test_create_price_unknown_unit_400(self):
        response = self.client.post(
            self.ledger_url("prices/"), self.price_payload(unit="ZZ"), format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_create_price_unknown_quote_unit_400(self):
        response = self.client.post(
            self.ledger_url("prices/"), self.price_payload(quote_unit="ZZ"), format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_list_prices_with_filters(self):
        self.client.post(self.ledger_url("prices/"), self.price_payload(), format="json")
        self.client.post(
            self.ledger_url("prices/"),
            self.price_payload(as_of="2026-02-01T00:00:00Z", price="3.0"),
            format="json",
        )
        r = self.client.get(self.ledger_url("prices/?unit=TU"))
        self.assertEqual(len(r.json()["results"]), 2)
        r = self.client.get(self.ledger_url("prices/?quote_unit=QU"))
        self.assertEqual(len(r.json()["results"]), 2)
        r = self.client.get(self.ledger_url("prices/?as_of_before=2026-01-15T00:00:00Z"))
        self.assertEqual(len(r.json()["results"]), 1)
        r = self.client.get(self.ledger_url("prices/?as_of_after=2026-01-15T00:00:00Z"))
        self.assertEqual(len(r.json()["results"]), 1)

    def test_viewer_cannot_write_price_403(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.post(
            self.ledger_url("prices/"), self.price_payload(), format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_viewer_cannot_read_prices_403(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.get(self.ledger_url("prices/"))
        self.assertEqual(response.status_code, 403)
