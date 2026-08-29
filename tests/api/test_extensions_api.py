import json
import os
from unittest import mock

from tests.api.base import NoetherAPITestCase
from tests.extensions_support import ensure_demo_registered

LEDGER_WRITE = "NOETHER_EXTENSIONS_LEDGER_WRITE"
ACCOUNT_WRITE = "NOETHER_EXTENSIONS_ACCOUNT_WRITE"
TXN_WRITE = "NOETHER_EXTENSIONS_TRANSACTION_WRITE"

SCHEMA = json.dumps(
    {
        "type": "object",
        "properties": {"cost_centre": {"type": "string"}},
        "additionalProperties": False,
    }
)


class ExtensionAPITests(NoetherAPITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        ensure_demo_registered()

    def test_ledger_create_with_env_extension(self):
        with mock.patch.dict(os.environ, {LEDGER_WRITE: SCHEMA}):
            response = self.client.post(
                "/api/v1/ledgers/",
                {
                    "domain": "testdomain",
                    "name": "Ext Ledger",
                    "extensions": {"core": {"cost_centre": "CC-1"}},
                },
                format="json",
            )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["extensions"]["core"], {"cost_centre": "CC-1"})

    def test_ledger_create_schema_violation_is_400(self):
        with mock.patch.dict(os.environ, {LEDGER_WRITE: SCHEMA}):
            response = self.client.post(
                "/api/v1/ledgers/",
                {
                    "domain": "testdomain",
                    "name": "Bad",
                    "extensions": {"core": {"cost_centre": 7}},
                },
                format="json",
            )
        self.assertEqual(response.status_code, 400, response.content)

    def test_unknown_extension_key_is_400(self):
        response = self.client.post(
            "/api/v1/ledgers/",
            {"domain": "testdomain", "name": "Bad", "extensions": {"nope": {}}},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_ledger_update_extensions(self):
        with mock.patch.dict(os.environ, {LEDGER_WRITE: SCHEMA}):
            response = self.client.put(
                f"/api/v1/ledgers/{self.ledger.external_id}/",
                {"name": "renamed", "extensions": {"core": {"cost_centre": "CC-2"}}},
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["extensions"]["core"], {"cost_centre": "CC-2"})

    def test_ledger_list_renders_extensions(self):
        response = self.client.get("/api/v1/ledgers/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("core", response.json()["results"][0]["extensions"])

    def test_account_create_and_render_plug_extension(self):
        with mock.patch.dict(os.environ, {ACCOUNT_WRITE: SCHEMA}):
            response = self.client.post(
                self.ledger_url("accounts/"),
                {
                    "name": "Ext Account",
                    "account_type": "generic",
                    "unit": str(self.unit.external_id),
                    "extensions": {
                        "demo": {"label": " boxed "},
                        "core": {"cost_centre": "CC-9"},
                    },
                },
                format="json",
            )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertEqual(body["extensions"]["demo"]["label"], "boxed")
        self.assertEqual(body["extensions"]["demo"]["rendered"], "retrieve")

        account_id = body["id"]
        listed = self.client.get(self.ledger_url("accounts/"))
        entry = next(a for a in listed.json()["results"] if a["id"] == account_id)
        self.assertEqual(entry["extensions"]["demo"]["rendered"], "list")

        retrieved = self.client.get(self.ledger_url(f"accounts/{account_id}/"))
        self.assertEqual(retrieved.json()["extensions"]["demo"]["rendered"], "retrieve")

    def test_account_plug_extension_rejects_bad_payload(self):
        response = self.client.post(
            self.ledger_url("accounts/"),
            {
                "name": "Bad Account",
                "account_type": "generic",
                "unit": str(self.unit.external_id),
                "extensions": {"demo": {"label": 42}},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_transaction_extensions_roundtrip(self):
        with mock.patch.dict(os.environ, {TXN_WRITE: SCHEMA}):
            created = self.create_txn(extensions={"core": {"cost_centre": "CC-T"}})
        self.assertEqual(created["extensions"]["core"], {"cost_centre": "CC-T"})

    def test_draft_transaction_extensions_editable(self):
        created = self.create_txn()
        with mock.patch.dict(os.environ, {TXN_WRITE: SCHEMA}):
            response = self.client.put(
                self.ledger_url(f"transactions/{created['id']}/"),
                {"extensions": {"core": {"cost_centre": "CC-D"}}},
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["extensions"]["core"], {"cost_centre": "CC-D"})

    def test_posted_transaction_extensions_immutable(self):
        """ADR-0012: extensions follow ADR-0001 — posted means frozen."""
        created = self.create_txn(post=True)
        with mock.patch.dict(os.environ, {TXN_WRITE: SCHEMA}):
            response = self.client.put(
                self.ledger_url(f"transactions/{created['id']}/"),
                {"extensions": {"core": {"cost_centre": "CC-X"}}},
                format="json",
            )
        self.assertEqual(response.status_code, 409, response.content)
