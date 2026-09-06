"""Client-supplied external ids and UUIDv7 generation (ADR-0016).

Two guarantees are under test:

1. Server-minted ``external_id`` values are UUIDv7 — time-ordered, so the
   unique index on ``external_id`` receives near-append-only inserts.
2. A client may supply the id on create. Replaying the same create with the
   same id and the same body returns the stored row (200); replaying it with a
   *different* body is a conflict (409) rather than a silent no-op.
"""

import uuid

from noether.ledger.models import Account, Ledger, Transaction, Unit
from noether.ledger.models_base import generate_external_id
from noether.ledger.tests.factories import AccountFactory, LedgerFactory, UnitFactory
from tests.api.base import OCCURRED, NoetherAPITestCase


class ExternalIdGenerationTests(NoetherAPITestCase):
    def test_generator_returns_stdlib_uuid_version_7(self):
        value = generate_external_id()
        self.assertIsInstance(value, uuid.UUID)
        self.assertEqual(value.version, 7)

    def test_generated_ids_are_time_ordered(self):
        values = [generate_external_id() for _ in range(50)]
        self.assertEqual(values, sorted(values))

    def test_generated_ids_are_unique(self):
        self.assertEqual(len({generate_external_id() for _ in range(500)}), 500)

    def test_models_default_to_version_7(self):
        for row in (LedgerFactory(), UnitFactory(), AccountFactory()):
            self.assertEqual(row.external_id.version, 7, type(row).__name__)


class ClientSuppliedIdCreateTests(NoetherAPITestCase):
    """POST with a client-chosen id, across a slugged and an unslugged model."""

    def unit_url(self):
        return self.ledger_url("units/")

    def unit_body(self, external_id, **extra):
        body = {"id": str(external_id), "symbol": "CSU", "name": "Client", "precision": 2}
        body.update(extra)
        return body

    def test_create_honours_client_supplied_id(self):
        external_id = generate_external_id()
        response = self.client.post(self.unit_url(), self.unit_body(external_id), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["id"], str(external_id))
        self.assertTrue(Unit.objects.filter(external_id=external_id).exists())

    def test_create_without_id_still_mints_one(self):
        response = self.client.post(
            self.unit_url(), {"symbol": "AUTO", "name": "Auto", "precision": 2}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        minted = Unit.objects.get(ledger=self.ledger, symbol="AUTO")
        self.assertEqual(minted.external_id.version, 7)

    def test_v4_id_is_rejected(self):
        """Only UUIDv7 is a valid identifier: no mixed-version id space."""
        response = self.client.post(self.unit_url(), self.unit_body(uuid.uuid4()), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("must be a UUIDv7", str(response.content))
        self.assertFalse(Unit.objects.filter(ledger=self.ledger, symbol="CSU").exists())

    def test_nil_uuid_is_rejected(self):
        """The all-zero UUID parses but has no version; it is not a v7."""
        response = self.client.post(
            self.unit_url(), self.unit_body("00000000-0000-0000-0000-000000000000"), format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("must be a UUIDv7", str(response.content))

    def test_malformed_id_is_rejected(self):
        response = self.client.post(self.unit_url(), self.unit_body("not-a-uuid"), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("must be a UUID", str(response.content))
        self.assertFalse(Unit.objects.filter(ledger=self.ledger, symbol="CSU").exists())

    def test_empty_id_is_treated_as_absent(self):
        response = self.client.post(self.unit_url(), self.unit_body(""), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Unit.objects.filter(ledger=self.ledger, symbol="CSU").count(), 1)

    def test_null_id_is_treated_as_absent(self):
        body = self.unit_body(generate_external_id())
        body["id"] = None
        response = self.client.post(self.unit_url(), body, format="json")
        self.assertEqual(response.status_code, 201, response.content)

    def test_replay_of_identical_body_returns_stored_row(self):
        external_id = generate_external_id()
        first = self.client.post(self.unit_url(), self.unit_body(external_id), format="json")
        self.assertEqual(first.status_code, 201, first.content)
        second = self.client.post(self.unit_url(), self.unit_body(external_id), format="json")
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(second.json()["id"], str(external_id))
        self.assertEqual(Unit.objects.filter(ledger=self.ledger, symbol="CSU").count(), 1)

    def test_replay_with_divergent_body_is_a_conflict(self):
        external_id = generate_external_id()
        self.client.post(self.unit_url(), self.unit_body(external_id), format="json")
        response = self.client.post(
            self.unit_url(), self.unit_body(external_id, name="Different"), format="json"
        )
        self.assertEqual(response.status_code, 409, response.content)
        self.assertIn("id_conflict", str(response.content))
        stored = Unit.objects.get(external_id=external_id)
        self.assertEqual(stored.name, "Client")

    def test_replay_does_not_bypass_authorization(self):
        external_id = generate_external_id()
        self.client.post(self.unit_url(), self.unit_body(external_id), format="json")
        self.client.force_authenticate(self.viewer)
        response = self.client.post(self.unit_url(), self.unit_body(external_id), format="json")
        self.assertEqual(response.status_code, 403, response.content)

    def test_replay_is_scoped_to_the_queryset(self):
        """An id belonging to another ledger is not a replay of this one."""
        other_ledger = LedgerFactory()
        stranger = UnitFactory(ledger=other_ledger, symbol="CSU", name="Client", precision=2)
        response = self.client.post(
            self.unit_url(), self.unit_body(stranger.external_id), format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("id_conflict", str(response.content))

    def test_deleted_row_id_cannot_be_reused(self):
        external_id = generate_external_id()
        self.client.post(self.unit_url(), self.unit_body(external_id), format="json")
        Unit.objects.filter(external_id=external_id).update(deleted=True)
        response = self.client.post(self.unit_url(), self.unit_body(external_id), format="json")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("id_conflict", str(response.content))


class AccountClientIdTests(NoetherAPITestCase):
    """FK-bearing resource: replay comparison must include relations."""

    def url(self):
        return self.ledger_url("accounts/")

    def body(self, external_id, **extra):
        body = {
            "id": str(external_id),
            "name": "Cash",
            "account_type": "generic",
            "unit": str(self.unit.external_id),
        }
        body.update(extra)
        return body

    def test_create_with_client_id(self):
        external_id = generate_external_id()
        response = self.client.post(self.url(), self.body(external_id), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(Account.objects.get(external_id=external_id).name, "Cash")

    def test_identical_replay_returns_stored_row(self):
        external_id = generate_external_id()
        self.client.post(self.url(), self.body(external_id), format="json")
        response = self.client.post(self.url(), self.body(external_id), format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Account.objects.filter(ledger=self.ledger, name="Cash").count(), 1)

    def test_divergent_parent_is_a_conflict(self):
        external_id = generate_external_id()
        self.client.post(self.url(), self.body(external_id), format="json")
        response = self.client.post(
            self.url(),
            self.body(external_id, parent=str(self.a.external_id)),
            format="json",
        )
        self.assertEqual(response.status_code, 409, response.content)

    def test_divergent_unit_is_a_conflict(self):
        external_id = generate_external_id()
        self.client.post(self.url(), self.body(external_id), format="json")
        other_unit = UnitFactory(ledger=self.ledger, symbol="OTH", precision=2)
        response = self.client.post(
            self.url(), self.body(external_id, unit=str(other_unit.external_id)), format="json"
        )
        self.assertEqual(response.status_code, 409, response.content)


class LedgerClientIdTests(NoetherAPITestCase):
    """Unscoped (non ledger-nested) collection."""

    def test_create_with_client_id(self):
        external_id = generate_external_id()
        response = self.client.post(
            "/api/v1/ledgers/",
            {"id": str(external_id), "domain": "testdomain", "name": "Client Ledger"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["id"], str(external_id))
        self.assertTrue(Ledger.objects.filter(external_id=external_id).exists())

    def test_identical_replay_returns_stored_row(self):
        external_id = generate_external_id()
        body = {"id": str(external_id), "domain": "testdomain", "name": "Client Ledger"}
        self.client.post("/api/v1/ledgers/", body, format="json")
        response = self.client.post("/api/v1/ledgers/", body, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Ledger.objects.filter(external_id=external_id).count(), 1)


class TransactionClientIdTests(NoetherAPITestCase):
    """The retry-sensitive path: an ambiguous POST must not double-post."""

    def url(self):
        return self.ledger_url("transactions/")

    def test_create_with_client_id(self):
        external_id = generate_external_id()
        response = self.client.post(
            self.url(), self.txn_payload(id=str(external_id)), format="json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["id"], str(external_id))

    def test_entries_receive_generated_v7_ids(self):
        response = self.client.post(self.url(), self.txn_payload(), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        for entry in response.json()["entries"]:
            self.assertEqual(uuid.UUID(entry["id"]).version, 7)

    def test_replay_does_not_double_post(self):
        external_id = generate_external_id()
        payload = self.txn_payload(post=True, id=str(external_id))
        first = self.client.post(self.url(), payload, format="json")
        self.assertEqual(first.status_code, 201, first.content)
        second = self.client.post(self.url(), payload, format="json")
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(Transaction.objects.filter(ledger=self.ledger).count(), 1)
        self.assertEqual(second.json()["status"], first.json()["status"])

    def test_replay_with_different_amount_is_a_conflict(self):
        external_id = generate_external_id()
        self.client.post(self.url(), self.txn_payload(id=str(external_id)), format="json")
        response = self.client.post(
            self.url(),
            self.txn_payload(amount="999.00", id=str(external_id)),
            format="json",
        )
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(Transaction.objects.filter(ledger=self.ledger).count(), 1)

    def test_replay_with_different_description_is_a_conflict(self):
        external_id = generate_external_id()
        self.client.post(self.url(), self.txn_payload(id=str(external_id)), format="json")
        response = self.client.post(
            self.url(),
            self.txn_payload(id=str(external_id), description="changed"),
            format="json",
        )
        self.assertEqual(response.status_code, 409, response.content)

    def test_replay_with_reordered_entries_is_a_conflict(self):
        """Entry order is part of the transaction's identity; no set semantics."""
        external_id = generate_external_id()
        self.client.post(self.url(), self.txn_payload(id=str(external_id)), format="json")
        payload = self.txn_payload(id=str(external_id))
        payload["entries"] = list(reversed(payload["entries"]))
        response = self.client.post(self.url(), payload, format="json")
        self.assertEqual(response.status_code, 409, response.content)

    def test_replay_with_extra_entry_is_a_conflict(self):
        external_id = generate_external_id()
        self.client.post(self.url(), self.txn_payload(id=str(external_id)), format="json")
        payload = self.txn_payload(id=str(external_id))
        payload["entries"].append(
            {"account": str(self.a.external_id), "direction": "debit", "amount": "1.00"}
        )
        response = self.client.post(self.url(), payload, format="json")
        self.assertEqual(response.status_code, 409, response.content)

    def test_malformed_id_rejected_before_any_write(self):
        response = self.client.post(self.url(), self.txn_payload(id="nope"), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Transaction.objects.filter(ledger=self.ledger).count(), 0)

    def test_replay_requires_create_permission(self):
        external_id = generate_external_id()
        self.client.post(self.url(), self.txn_payload(id=str(external_id)), format="json")
        self.client.force_authenticate(self.viewer)
        response = self.client.post(
            self.url(), self.txn_payload(id=str(external_id)), format="json"
        )
        self.assertEqual(response.status_code, 403, response.content)

    def test_client_id_survives_posting(self):
        external_id = generate_external_id()
        response = self.client.post(
            self.url(), self.txn_payload(post=True, id=str(external_id)), format="json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["id"], str(external_id))
        stored = Transaction.objects.get(ledger=self.ledger)
        self.assertEqual(str(stored.external_id), str(external_id))

    def test_occurred_at_divergence_is_a_conflict(self):
        external_id = generate_external_id()
        self.client.post(self.url(), self.txn_payload(id=str(external_id)), format="json")
        response = self.client.post(
            self.url(),
            self.txn_payload(id=str(external_id), occurred_at="2026-02-01T00:00:00Z"),
            format="json",
        )
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(OCCURRED, "2026-01-15T00:00:00Z")
