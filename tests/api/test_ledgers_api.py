from noether.ledger.models import Account, Ledger, Unit
from noether.ledger.tests.factories import UserFactory
from noether.security.models import LedgerUser as SecurityLedgerUser
from tests.api.base import NoetherAPITestCase


class DomainAPITests(NoetherAPITestCase):
    def test_list_domains(self):
        response = self.client.get("/api/v1/domains/")
        self.assertEqual(response.status_code, 200)
        slugs = [d["slug"] for d in response.json()["results"]]
        self.assertIn("testdomain", slugs)

    def test_retrieve_domain(self):
        response = self.client.get("/api/v1/domains/testdomain/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["slug"], "testdomain")
        self.assertEqual(body["account_types"][0]["name"], "generic")
        self.assertEqual(body["chart_templates"][0]["name"], "default")

    def test_retrieve_unknown_domain_404(self):
        response = self.client.get("/api/v1/domains/nope/")
        self.assertEqual(response.status_code, 404)


class RoleAPITests(NoetherAPITestCase):
    def test_list_roles(self):
        response = self.client.get("/api/v1/roles/")
        self.assertEqual(response.status_code, 200)
        names = [r["name"] for r in response.json()["results"]]
        for expected in ["Owner", "Bookkeeper", "Auditor", "Viewer"]:
            self.assertIn(expected, names)


class LedgerAPITests(NoetherAPITestCase):
    def test_create_ledger_with_chart(self):
        response = self.client.post(
            "/api/v1/ledgers/",
            {"domain": "testdomain", "name": "My Ledger", "chart_template": "default"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        ledger = Ledger.objects.get(external_id=body["id"])
        self.assertEqual(Unit.objects.filter(ledger=ledger).count(), 2)
        self.assertTrue(
            Account.objects.filter(ledger=ledger, name="Main").exists()
        )
        # creator becomes Owner member
        self.assertTrue(
            SecurityLedgerUser.objects.filter(
                ledger=ledger, user=self.owner, role__name="Owner"
            ).exists()
        )

    def test_create_ledger_without_chart(self):
        response = self.client.post(
            "/api/v1/ledgers/", {"domain": "testdomain", "name": "Bare"}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        ledger = Ledger.objects.get(external_id=response.json()["id"])
        self.assertEqual(Account.objects.filter(ledger=ledger).count(), 0)

    def test_create_ledger_unknown_domain_400(self):
        response = self.client.post(
            "/api/v1/ledgers/", {"domain": "nope", "name": "X"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_create_ledger_unknown_chart_400(self):
        response = self.client.post(
            "/api/v1/ledgers/",
            {"domain": "testdomain", "name": "X", "chart_template": "nope"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_list_only_accessible(self):
        response = self.client.get("/api/v1/ledgers/")
        ids = [ledger["id"] for ledger in response.json()["results"]]
        self.assertEqual(ids, [str(self.ledger.external_id)])

    def test_retrieve(self):
        response = self.client.get(f"/api/v1/ledgers/{self.ledger.external_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["domain"], "testdomain")

    def test_update(self):
        response = self.client.patch(
            f"/api/v1/ledgers/{self.ledger.external_id}/",
            {"name": "Renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Renamed")

    def test_soft_delete_owner_only(self):
        response = self.client.delete(f"/api/v1/ledgers/{self.ledger.external_id}/")
        self.assertEqual(response.status_code, 204)
        self.ledger.refresh_from_db()
        self.assertTrue(self.ledger.deleted)
        # soft-deleted → inaccessible
        response = self.client.get(f"/api/v1/ledgers/{self.ledger.external_id}/")
        self.assertEqual(response.status_code, 404)

    def test_viewer_cannot_delete_403(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.delete(f"/api/v1/ledgers/{self.ledger.external_id}/")
        self.assertEqual(response.status_code, 403)

    def test_viewer_cannot_update_403(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.patch(
            f"/api/v1/ledgers/{self.ledger.external_id}/", {"name": "N"}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_outsider_retrieve_404(self):
        self.client.force_authenticate(self.outsider)
        response = self.client.get(f"/api/v1/ledgers/{self.ledger.external_id}/")
        self.assertEqual(response.status_code, 404)


class MemberAPITests(NoetherAPITestCase):
    def test_list_members(self):
        response = self.client.get(self.ledger_url("members/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 2)

    def test_add_member(self):
        newbie = UserFactory()
        response = self.client.post(
            self.ledger_url("members/"),
            {"user": newbie.username, "role": "Auditor"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            SecurityLedgerUser.objects.filter(
                ledger=self.ledger, user=newbie, role__name="Auditor"
            ).exists()
        )

    def test_add_member_unknown_user_400(self):
        response = self.client.post(
            self.ledger_url("members/"), {"user": "ghost", "role": "Auditor"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_add_member_unknown_role_400(self):
        newbie = UserFactory()
        response = self.client.post(
            self.ledger_url("members/"),
            {"user": newbie.username, "role": "God"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_change_member_role(self):
        membership = SecurityLedgerUser.objects.get(ledger=self.ledger, user=self.viewer)
        response = self.client.put(
            self.ledger_url(f"members/{membership.external_id}/"),
            {"role": "Auditor"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        membership.refresh_from_db()
        self.assertEqual(membership.role.name, "Auditor")

    def test_remove_member(self):
        membership = SecurityLedgerUser.objects.get(ledger=self.ledger, user=self.viewer)
        response = self.client.delete(self.ledger_url(f"members/{membership.external_id}/"))
        self.assertEqual(response.status_code, 204)
        self.assertFalse(
            SecurityLedgerUser.objects.filter(pk=membership.pk).exists()
        )

    def test_viewer_cannot_manage_members_403(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.post(
            self.ledger_url("members/"),
            {"user": self.outsider.username, "role": "Viewer"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
