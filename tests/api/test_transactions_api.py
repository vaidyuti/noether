from noether.ledger.models import Transaction, TransactionStatus
from tests.api.base import NoetherAPITestCase


class TransactionAPITests(NoetherAPITestCase):
    def test_create_draft(self):
        data = self.create_txn()
        self.assertEqual(data["status"], "draft")
        self.assertEqual(data["entries"][0]["amount"], "100.0000000000")

    def test_create_and_post_directly(self):
        data = self.create_txn(post=True)
        self.assertEqual(data["status"], "posted")
        self.assertIsNotNone(data["posted_at"])

    def test_list_filters(self):
        self.create_txn()
        self.create_txn(post=True)
        response = self.client.get(self.ledger_url("transactions/?status=posted"))
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "posted")

    def test_list_filter_by_account(self):
        self.create_txn()
        url = self.ledger_url(f"transactions/?account={self.a.external_id}")
        self.assertEqual(len(self.client.get(url).json()["results"]), 1)

    def test_list_filter_occurred_window(self):
        self.create_txn()
        r = self.client.get(self.ledger_url("transactions/?occurred_after=2026-01-01T00:00:00Z"))
        self.assertEqual(len(r.json()["results"]), 1)
        r = self.client.get(self.ledger_url("transactions/?occurred_before=2026-01-01T00:00:00Z"))
        self.assertEqual(len(r.json()["results"]), 0)

    def test_retrieve(self):
        data = self.create_txn()
        response = self.client.get(self.ledger_url(f"transactions/{data['id']}/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], data["id"])

    def test_post_action(self):
        data = self.create_txn()
        response = self.client.post(self.ledger_url(f"transactions/{data['id']}/post/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "posted")

    def test_post_unbalanced_400_conservation_error(self):
        payload = self.txn_payload()
        payload["entries"][0]["amount"] = "500.00"
        payload["entries"][1]["amount"] = "400.00"
        payload["post"] = True
        response = self.client.post(self.ledger_url("transactions/"), payload, format="json")
        self.assertEqual(response.status_code, 400)
        error = response.json()["errors"][0]
        self.assertEqual(error["type"], "conservation_error")
        self.assertEqual(error["msg"], "unit TU: debits 500.00 != credits 400.00")

    def test_repost_409(self):
        data = self.create_txn(post=True)
        response = self.client.post(self.ledger_url(f"transactions/{data['id']}/post/"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["errors"][0]["type"], "immutable_transaction")

    def test_edit_posted_409(self):
        data = self.create_txn(post=True)
        response = self.client.patch(
            self.ledger_url(f"transactions/{data['id']}/"),
            {"description": "hax"},
            format="json",
        )
        self.assertEqual(response.status_code, 409)

    def test_delete_posted_409(self):
        data = self.create_txn(post=True)
        response = self.client.delete(self.ledger_url(f"transactions/{data['id']}/"))
        self.assertEqual(response.status_code, 409)

    def test_edit_draft_ok(self):
        data = self.create_txn()
        response = self.client.patch(
            self.ledger_url(f"transactions/{data['id']}/"),
            {"description": "edited"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["description"], "edited")

    def test_delete_draft_hard_deletes(self):
        data = self.create_txn()
        response = self.client.delete(self.ledger_url(f"transactions/{data['id']}/"))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Transaction.objects.filter(external_id=data["id"]).exists())

    def test_reverse_action(self):
        data = self.create_txn(post=True)
        response = self.client.post(
            self.ledger_url(f"transactions/{data['id']}/reverse/"), {}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        mirror = response.json()
        self.assertEqual(mirror["reverses"], data["id"])
        original = Transaction.objects.get(external_id=data["id"])
        self.assertEqual(original.status, TransactionStatus.REVERSED)

    def test_reverse_with_body(self):
        data = self.create_txn(post=True)
        response = self.client.post(
            self.ledger_url(f"transactions/{data['id']}/reverse/"),
            {"description": "undo", "occurred_at": "2026-02-01T00:00:00Z"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["description"], "undo")

    def test_reverse_draft_409(self):
        data = self.create_txn()
        response = self.client.post(
            self.ledger_url(f"transactions/{data['id']}/reverse/"), {}, format="json"
        )
        self.assertEqual(response.status_code, 409)

    def test_re_reverse_409(self):
        data = self.create_txn(post=True)
        self.client.post(self.ledger_url(f"transactions/{data['id']}/reverse/"), {}, format="json")
        response = self.client.post(
            self.ledger_url(f"transactions/{data['id']}/reverse/"), {}, format="json"
        )
        self.assertEqual(response.status_code, 409)

    def test_domain_validator_400(self):
        self.b.metadata = {"non_negative": True}
        self.b.save()
        response = self.client.post(
            self.ledger_url("transactions/"), self.txn_payload(post=True), format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"][0]["type"], "domain_validation_error")

    def test_unknown_account_400(self):
        payload = self.txn_payload()
        payload["entries"][0]["account"] = "00000000-0000-0000-0000-000000000000"
        response = self.client.post(self.ledger_url("transactions/"), payload, format="json")
        self.assertEqual(response.status_code, 400)

    def test_invalid_direction_400(self):
        payload = self.txn_payload()
        payload["entries"][0]["direction"] = "sideways"
        response = self.client.post(self.ledger_url("transactions/"), payload, format="json")
        self.assertEqual(response.status_code, 400)

    def test_amount_accepts_number(self):
        payload = self.txn_payload()
        payload["entries"][0]["amount"] = 100
        payload["entries"][1]["amount"] = 100
        response = self.client.post(self.ledger_url("transactions/"), payload, format="json")
        self.assertEqual(response.status_code, 201)

    def test_viewer_cannot_create_403(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.post(
            self.ledger_url("transactions/"), self.txn_payload(), format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_viewer_cannot_list_transactions_403(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.get(self.ledger_url("transactions/"))
        self.assertEqual(response.status_code, 403)

    def test_outsider_gets_404(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.get(self.ledger_url("transactions/"))
        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_401(self):
        self.client.force_authenticate(None)
        response = self.client.get(self.ledger_url("transactions/"))
        self.assertEqual(response.status_code, 401)

    def test_retrieve_missing_404(self):
        response = self.client.get(
            self.ledger_url("transactions/00000000-0000-0000-0000-000000000000/")
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["errors"][0]["type"], "object_not_found")

    def test_invalid_body_pydantic_400(self):
        response = self.client.post(
            self.ledger_url("transactions/"), {"description": "no entries"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("errors", response.json())
