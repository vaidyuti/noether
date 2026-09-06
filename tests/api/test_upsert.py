"""Bulk upsert mixin: identity resolution, batching, rollback, authorization."""

import uuid
from unittest import mock

from django.core.exceptions import FieldDoesNotExist
from django.test import override_settings
from rest_framework.exceptions import ValidationError as RestFrameworkValidationError

from noether.api.viewsets.base import NoetherUpsertMixin, extract_client_external_id
from noether.ledger.models import Account, Unit
from tests.api.base import NoetherAPITestCase

EXAMPLE_ID = uuid.UUID("01920000-0000-7000-8000-000000000002")


class _FakeMeta:
    def __init__(self, names):
        self._names = names

    def get_field(self, name):
        if name not in self._names:
            raise FieldDoesNotExist(name)
        return object()


class _FakeModel:
    def __init__(self, names):
        self._meta = _FakeMeta(names)


class IdentityResolutionUnitTests(NoetherAPITestCase):
    """The identity rule is feature-detected off the model's _meta."""

    def test_model_without_slug_field_is_detected(self):
        view = NoetherUpsertMixin()
        view.database_model = Unit
        self.assertFalse(view.model_has_slug_field())

    def test_model_with_slug_field_is_detected(self):
        view = NoetherUpsertMixin()
        view.database_model = _FakeModel({"slug"})
        self.assertTrue(view.model_has_slug_field())

    def test_identity_prefers_slug_when_model_supports_it(self):
        view = NoetherUpsertMixin()
        view.database_model = _FakeModel({"slug"})
        self.assertEqual(view.resolve_identity({"slug": "cash", "id": "x"}), ("slug", "cash"))

    def test_identity_falls_back_to_external_id(self):
        view = NoetherUpsertMixin()
        view.database_model = Unit
        self.assertEqual(
            view.resolve_identity({"slug": "cash", "id": str(EXAMPLE_ID)}),
            ("external_id", EXAMPLE_ID),
        )

    def test_identity_none_when_no_identifier(self):
        view = NoetherUpsertMixin()
        view.database_model = Unit
        self.assertIsNone(view.resolve_identity({"name": "n"}))

    def test_identity_none_when_slug_model_has_neither_key(self):
        view = NoetherUpsertMixin()
        view.database_model = _FakeModel({"slug"})
        self.assertIsNone(view.resolve_identity({"name": "n"}))

    def test_identity_slug_model_falls_back_to_id(self):
        view = NoetherUpsertMixin()
        view.database_model = _FakeModel({"slug"})
        self.assertEqual(
            view.resolve_identity({"id": str(EXAMPLE_ID)}), ("external_id", EXAMPLE_ID)
        )

    def test_identity_rejects_a_malformed_id(self):
        view = NoetherUpsertMixin()
        view.database_model = Unit
        with self.assertRaises(RestFrameworkValidationError):
            view.resolve_identity({"id": "not-a-uuid"})

    def test_extract_client_external_id_ignores_non_dict_bodies(self):
        """Body shape is validated elsewhere; the extractor just declines."""
        self.assertIsNone(extract_client_external_id(["not", "a", "dict"]))


class UnitUpsertAPITests(NoetherAPITestCase):
    url = None

    def setUp(self):
        super().setUp()
        self.url = self.ledger_url("units/upsert/")

    def post(self, body):
        return self.client.post(self.url, body, format="json")

    # --- malformed bodies -------------------------------------------------
    def test_non_dict_body_rejected(self):
        response = self.post([{"symbol": "X"}])
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid request body", str(response.content))

    def test_non_list_datapoints_rejected(self):
        response = self.post({"datapoints": {"symbol": "X"}})
        self.assertEqual(response.status_code, 400)
        self.assertIn("must be a list", str(response.content))

    def test_empty_datapoints_rejected(self):
        response = self.post({"datapoints": []})
        self.assertEqual(response.status_code, 400)
        self.assertIn("No datapoints", str(response.content))

    def test_non_dict_datapoint_rejected(self):
        response = self.post({"datapoints": ["nope"]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("must be an object", str(response.content))

    @override_settings(MAX_DATAPOINTS_PER_UPSERT=2)
    def test_oversized_batch_rejected(self):
        body = {"datapoints": [{"symbol": f"S{i}", "name": "n"} for i in range(3)]}
        response = self.post(body)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Too many datapoints", str(response.content))

    def test_duplicate_identifier_in_batch_rejected(self):
        body = {
            "datapoints": [
                {"id": str(self.unit.external_id), "name": "one"},
                {"id": str(self.unit.external_id), "name": "two"},
            ]
        }
        response = self.post(body)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Duplicate identifier", str(response.content))
        self.unit.refresh_from_db()
        self.assertNotEqual(self.unit.name, "one")

    # --- happy paths ------------------------------------------------------
    def test_create_path(self):
        response = self.post({"datapoints": [{"symbol": "NEW", "name": "New", "precision": 2}]})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()[0]["symbol"], "NEW")
        self.assertTrue(Unit.objects.filter(ledger=self.ledger, symbol="NEW").exists())

    def test_update_path_when_identifier_matches(self):
        body = {"datapoints": [{"id": str(self.unit.external_id), "name": "Renamed"}]}
        response = self.post(body)
        self.assertEqual(response.status_code, 200, response.content)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.name, "Renamed")

    def test_unmatched_identifier_creates_with_the_supplied_id(self):
        """Supersedes ADR-0015's mint-a-fresh-id behaviour: the client's id wins.

        The whole point of a client-chosen id is that re-running the import
        addresses the same row; minting a different one would make the second
        run a duplicate rather than a no-op (ADR-0016).
        """
        body = {
            "datapoints": [
                {
                    "id": str(EXAMPLE_ID),
                    "symbol": "GHOST",
                    "name": "Ghost",
                }
            ]
        }
        response = self.post(body)
        self.assertEqual(response.status_code, 200, response.content)
        created = Unit.objects.get(ledger=self.ledger, symbol="GHOST")
        self.assertEqual(str(created.external_id), str(EXAMPLE_ID))

    def test_malformed_identifier_is_rejected(self):
        """Supersedes ADR-0015: a malformed id is a client error, not a create."""
        body = {
            "datapoints": [{"id": "not-a-uuid", "symbol": "MAL", "name": "Mal", "precision": 2}]
        }
        response = self.post(body)
        self.assertEqual(response.status_code, 400)
        self.assertIn("must be a UUID", str(response.content))
        self.assertFalse(Unit.objects.filter(ledger=self.ledger, symbol="MAL").exists())

    def test_mixed_create_and_update_batch(self):
        body = {
            "datapoints": [
                {"id": str(self.unit.external_id), "name": "Updated"},
                {"symbol": "MIX", "name": "Mixed", "precision": 1},
            ]
        }
        response = self.post(body)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()), 2)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.name, "Updated")
        self.assertTrue(Unit.objects.filter(ledger=self.ledger, symbol="MIX").exists())

    def test_idempotent_reimport(self):
        body = {"datapoints": [{"symbol": "IDEM", "name": "Idem", "precision": 2}]}
        first = self.post(body)
        self.assertEqual(first.status_code, 200, first.content)
        identifier = first.json()[0]["id"]
        again = self.post({"datapoints": [{"id": identifier, "name": "Idem"}]})
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(Unit.objects.filter(ledger=self.ledger, symbol="IDEM").count(), 1)

    # --- failure semantics ------------------------------------------------
    def test_one_failure_rolls_back_whole_batch(self):
        before = set(Unit.objects.filter(ledger=self.ledger).values_list("symbol", flat=True))
        body = {
            "datapoints": [
                {"symbol": "OK1", "name": "Ok", "precision": 2},
                {"symbol": "BAD", "name": "Bad", "precision": 99},
            ]
        }
        response = self.post(body)
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["symbol"], "OK1")
        self.assertIn("precision", str(payload[1]))
        after = set(Unit.objects.filter(ledger=self.ledger).values_list("symbol", flat=True))
        self.assertEqual(before, after)

    def test_unhandled_exception_propagates(self):
        body = {"datapoints": [{"symbol": "BOOM", "name": "Boom", "precision": 2}]}
        with (
            mock.patch(
                "noether.ledger.api.units.UnitViewSet.handle_create",
                side_effect=RuntimeError("kaboom"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.post(body)

    def test_authorization_denied_per_datapoint(self):
        self.client.force_authenticate(self.viewer)
        response = self.post({"datapoints": [{"symbol": "NOPE", "name": "Nope", "precision": 2}]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("permission_denied", str(response.content))
        self.assertFalse(Unit.objects.filter(ledger=self.ledger, symbol="NOPE").exists())


class AccountUpsertAPITests(NoetherAPITestCase):
    def setUp(self):
        super().setUp()
        self.url = self.ledger_url("accounts/upsert/")

    def test_chart_of_accounts_import_is_idempotent(self):
        payload = {
            "datapoints": [
                {
                    "name": "Cash",
                    "account_type": "generic",
                    "unit": str(self.unit.external_id),
                },
                {
                    "name": "Revenue",
                    "account_type": "boundary",
                    "unit": str(self.unit.external_id),
                },
            ]
        }
        first = self.client.post(self.url, payload, format="json")
        self.assertEqual(first.status_code, 200, first.content)
        ids = [row["id"] for row in first.json()]
        second = self.client.post(
            self.url,
            {
                "datapoints": [
                    {"id": i, "name": n} for i, n in zip(ids, ["Cash", "Revenue"], strict=True)
                ]
            },
            format="json",
        )
        self.assertEqual(second.status_code, 200, second.content)
        self.assertEqual(Account.objects.filter(ledger=self.ledger, name="Cash").count(), 1)
