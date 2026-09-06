"""Tagging: model hierarchy caches, tag manager, filter, REST surface (ADR-0013)."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from noether.ledger.models import TagConfig, Transaction
from noether.ledger.models_base import generate_external_id
from noether.ledger.resources.tag.constants import TagResource
from noether.ledger.tests.factories import LedgerFactory, TransactionFactory, UserFactory
from noether.security.authorization.base import PermissionDeniedError
from noether.security.models import LedgerUser as SecurityLedgerUser
from noether.security.models import Role
from noether.tagging.base import BaseTagManager, LedgerTagManager
from noether.tagging.filters import TagFilter
from tests.api.base import NoetherAPITestCase


def make_tag(ledger, display, *, parent=None, exclusive_children=False, resource="transaction"):
    return TagConfig.objects.create(
        ledger=ledger,
        display=display,
        resource=resource,
        parent=parent,
        exclusive_children=exclusive_children,
    )


class TagConfigHierarchyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ledger = LedgerFactory()

    def test_root_has_no_ancestry(self):
        root = make_tag(self.ledger, "root")
        self.assertEqual(root.level_cache, 0)
        self.assertEqual(root.parent_cache, [])
        self.assertIsNone(root.root_tag_config)
        self.assertFalse(root.has_children)
        self.assertEqual(root.get_parent_json(), {})

    def test_deep_nesting_maintains_caches(self):
        root = make_tag(self.ledger, "root")
        child = make_tag(self.ledger, "child", parent=root)
        grandchild = make_tag(self.ledger, "grandchild", parent=child)
        great = make_tag(self.ledger, "great", parent=grandchild)

        self.assertEqual(child.level_cache, 1)
        self.assertEqual(child.parent_cache, [root.id])
        self.assertEqual(child.root_tag_config_id, root.id)

        self.assertEqual(grandchild.level_cache, 2)
        self.assertEqual(grandchild.parent_cache, [root.id, child.id])
        self.assertEqual(grandchild.root_tag_config_id, root.id)

        self.assertEqual(great.level_cache, 3)
        self.assertEqual(great.parent_cache, [root.id, child.id, grandchild.id])
        self.assertEqual(great.root_tag_config_id, root.id)

        root.refresh_from_db()
        child.refresh_from_db()
        self.assertTrue(root.has_children)
        self.assertTrue(child.has_children)

    def test_second_child_does_not_re_flag_parent(self):
        root = make_tag(self.ledger, "root")
        make_tag(self.ledger, "a", parent=root)
        root.refresh_from_db()
        modified_first = root.modified_date
        make_tag(self.ledger, "b", parent=root)
        root.refresh_from_db()
        self.assertTrue(root.has_children)
        self.assertEqual(root.modified_date, modified_first)

    def test_update_does_not_recompute_hierarchy(self):
        root = make_tag(self.ledger, "root")
        child = make_tag(self.ledger, "child", parent=root)
        child.display = "renamed"
        child.save()
        child.refresh_from_db()
        self.assertEqual(child.display, "renamed")
        self.assertEqual(child.parent_cache, [root.id])

    def test_parent_json_populates_and_is_reused(self):
        root = make_tag(self.ledger, "root")
        child = make_tag(self.ledger, "child", parent=root)
        grandchild = make_tag(self.ledger, "grandchild", parent=child)

        blob = grandchild.get_parent_json()
        self.assertEqual(blob["display"], "child")
        self.assertEqual(blob["parent"]["display"], "root")
        self.assertEqual(blob["parent"]["parent"], {})
        self.assertEqual(blob["level_cache"], 1)

        grandchild.refresh_from_db()
        self.assertTrue(grandchild.cached_parent_json)
        # second call hits the cache: mutating the parent must not show through
        child.display = "changed"
        child.save(update_fields=["display"])
        self.assertEqual(grandchild.get_parent_json()["display"], "child")

    def test_parent_json_expiry_forces_recompute(self):
        root = make_tag(self.ledger, "root")
        child = make_tag(self.ledger, "child", parent=root)
        child.get_parent_json()
        child.refresh_from_db()
        stale = dict(child.cached_parent_json)
        stale["cache_expiry"] = (timezone.now() - timedelta(days=1)).isoformat()
        stale["display"] = "stale"
        TagConfig.objects.filter(id=child.id).update(cached_parent_json=stale)
        child.refresh_from_db()
        self.assertEqual(child.get_parent_json()["display"], "root")


class BaseTagManagerProtocolTests(TestCase):
    """The abstract protocol: defaults work, hooks raise until overridden."""

    def setUp(self):
        self.manager = BaseTagManager()

    def test_get_resource_tags_defaults_to_empty(self):
        class Row:
            tags = None

        self.assertEqual(self.manager.get_resource_tags(Row()), [])

    def test_get_resource_tags_returns_existing(self):
        class Row:
            tags = [1, 2]

        self.assertEqual(self.manager.get_resource_tags(Row()), [1, 2])

    def test_set_instance_tags_writes_and_reports_field(self):
        class Row:
            tags = []

        row = Row()
        self.assertEqual(self.manager.set_instance_tags(row, [3]), ["tags"])
        self.assertEqual(row.tags, [3])

    def test_abstract_hooks_raise(self):
        with self.assertRaises(NotImplementedError):
            self.manager.get_tag_config_object(generate_external_id())
        with self.assertRaises(NotImplementedError):
            self.manager.set_tag("transaction", None, None, None)
        with self.assertRaises(NotImplementedError):
            self.manager.unset_tag(None, None, None)
        with self.assertRaises(NotImplementedError):
            self.manager.render_tags(None)

    def test_bulk_helpers_delegate_to_singular(self):
        seen = []

        class Recorder(BaseTagManager):
            def set_tag(self, resource_type, resource, tag, user):
                seen.append(("set", tag))

            def unset_tag(self, resource, tag, user):
                seen.append(("unset", tag))

        recorder = Recorder()
        recorder.set_tags("transaction", None, ["a", "b"], None)
        recorder.unset_tags(None, ["a"], None)
        self.assertEqual(seen, [("set", "a"), ("set", "b"), ("unset", "a")])


class LedgerTagManagerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("sync_permissions_roles")
        cls.ledger = LedgerFactory()
        cls.other_ledger = LedgerFactory()
        cls.owner = UserFactory()
        cls.auditor = UserFactory()
        SecurityLedgerUser.objects.create(
            ledger=cls.ledger, user=cls.owner, role=Role.objects.get(name="Owner")
        )
        SecurityLedgerUser.objects.create(
            ledger=cls.ledger, user=cls.auditor, role=Role.objects.get(name="Auditor")
        )

    def setUp(self):
        self.manager = LedgerTagManager(self.ledger)
        self.txn = TransactionFactory(ledger=self.ledger)

    def apply(self, tag, user=None):
        self.manager.set_tag(TagResource.transaction, self.txn, tag.external_id, user or self.owner)

    def test_set_and_unset_roundtrip(self):
        tag = make_tag(self.ledger, "alpha")
        self.apply(tag)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.tags, [tag.id])
        self.manager.unset_tag(self.txn, tag.external_id, self.owner)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.tags, [])

    def test_unknown_tag_rejected(self):
        with self.assertRaisesMessage(ValidationError, "unknown tag"):
            self.manager.set_tag(
                TagResource.transaction, self.txn, generate_external_id(), self.owner
            )

    def test_cross_ledger_tag_rejected(self):
        foreign = make_tag(self.other_ledger, "foreign")
        with self.assertRaisesMessage(ValidationError, "unknown tag"):
            self.apply(foreign)

    def test_soft_deleted_tag_rejected(self):
        tag = make_tag(self.ledger, "gone")
        TagConfig.objects.filter(id=tag.id).update(deleted=True)
        with self.assertRaisesMessage(ValidationError, "unknown tag"):
            self.apply(tag)

    def test_resource_mismatch_rejected(self):
        tag = make_tag(self.ledger, "acct", resource="account")
        with self.assertRaisesMessage(ValidationError, "applies to account"):
            self.apply(tag)

    def test_duplicate_apply_rejected(self):
        tag = make_tag(self.ledger, "alpha")
        self.apply(tag)
        self.txn.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "already applied"):
            self.apply(tag)

    def test_unset_not_applied_rejected(self):
        tag = make_tag(self.ledger, "alpha")
        with self.assertRaisesMessage(ValidationError, "is not applied"):
            self.manager.unset_tag(self.txn, tag.external_id, self.owner)

    def test_permission_denied_for_auditor(self):
        tag = make_tag(self.ledger, "alpha")
        with self.assertRaisesMessage(PermissionDeniedError, "missing permission to apply"):
            self.apply(tag, user=self.auditor)

    def test_permission_denied_on_unset(self):
        tag = make_tag(self.ledger, "alpha")
        self.apply(tag)
        self.txn.refresh_from_db()
        with self.assertRaisesMessage(PermissionDeniedError, "missing permission to remove"):
            self.manager.unset_tag(self.txn, tag.external_id, self.auditor)

    # --- exclusivity: both branches -------------------------------------

    def test_non_exclusive_siblings_coexist(self):
        parent = make_tag(self.ledger, "colour", exclusive_children=False)
        red = make_tag(self.ledger, "red", parent=parent)
        blue = make_tag(self.ledger, "blue", parent=parent)
        self.apply(red)
        self.txn.refresh_from_db()
        self.apply(blue)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.tags, [red.id, blue.id])

    def test_exclusive_parent_rejects_sibling(self):
        parent = make_tag(self.ledger, "colour", exclusive_children=True)
        red = make_tag(self.ledger, "red", parent=parent)
        blue = make_tag(self.ledger, "blue", parent=parent)
        self.apply(red)
        self.txn.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "allows only one tag from its subtree"):
            self.apply(blue)

    def test_exclusive_ancestor_rejects_deep_cousin(self):
        root = make_tag(self.ledger, "colour", exclusive_children=True)
        warm = make_tag(self.ledger, "warm", parent=root)
        cool = make_tag(self.ledger, "cool", parent=root)
        red = make_tag(self.ledger, "red", parent=warm)
        blue = make_tag(self.ledger, "blue", parent=cool)
        self.apply(red)
        self.txn.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "allows only one tag from its subtree"):
            self.apply(blue)

    def test_exclusive_ancestor_allows_unrelated_subtree(self):
        exclusive = make_tag(self.ledger, "colour", exclusive_children=True)
        red = make_tag(self.ledger, "red", parent=exclusive)
        other_root = make_tag(self.ledger, "size")
        big = make_tag(self.ledger, "big", parent=other_root)
        self.apply(red)
        self.txn.refresh_from_db()
        self.apply(big)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.tags, [red.id, big.id])

    def test_exclusive_ancestor_with_no_conflict_allows_apply(self):
        """Exclusive ancestor is consulted, finds nothing applied from its subtree."""
        exclusive = make_tag(self.ledger, "colour", exclusive_children=True)
        red = make_tag(self.ledger, "red", parent=exclusive)
        unrelated = make_tag(self.ledger, "unrelated")
        self.apply(unrelated)
        self.txn.refresh_from_db()
        self.apply(red)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.tags, [unrelated.id, red.id])

    def test_root_tag_skips_exclusivity_check(self):
        root_a = make_tag(self.ledger, "a")
        root_b = make_tag(self.ledger, "b")
        self.apply(root_a)
        self.txn.refresh_from_db()
        self.apply(root_b)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.tags, [root_a.id, root_b.id])

    def test_child_of_non_exclusive_ancestors_allowed(self):
        root = make_tag(self.ledger, "root", exclusive_children=False)
        mid = make_tag(self.ledger, "mid", parent=root, exclusive_children=False)
        leaf = make_tag(self.ledger, "leaf", parent=mid)
        other = make_tag(self.ledger, "other")
        self.apply(other)
        self.txn.refresh_from_db()
        self.apply(leaf)
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.tags, [other.id, leaf.id])

    def test_render_tags(self):
        first = make_tag(self.ledger, "first")
        second = make_tag(self.ledger, "second")
        self.apply(first)
        self.txn.refresh_from_db()
        self.apply(second)
        self.txn.refresh_from_db()
        rendered = self.manager.render_tags(self.txn)
        self.assertEqual([r["display"] for r in rendered], ["first", "second"])

    def test_render_tags_empty(self):
        self.assertEqual(self.manager.render_tags(self.txn), [])


class TagFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ledger = LedgerFactory()
        cls.red = make_tag(cls.ledger, "red")
        cls.blue = make_tag(cls.ledger, "blue")

    def setUp(self):
        self.qs = Transaction.objects.all()
        self.red_txn = TransactionFactory(ledger=self.ledger, tags=[self.red.id])
        self.both_txn = TransactionFactory(ledger=self.ledger, tags=[self.red.id, self.blue.id])
        self.untagged = TransactionFactory(ledger=self.ledger)

    def test_empty_value_passes_through(self):
        self.assertEqual(TagFilter().filter(self.qs, "").count(), 3)

    def test_matching_single_tag(self):
        result = TagFilter().filter(self.qs, str(self.blue.external_id))
        self.assertEqual(list(result), [self.both_txn])

    def test_multiple_tags_any(self):
        value = f"{self.red.external_id}, {self.blue.external_id}"
        self.assertEqual(TagFilter().filter(self.qs, value).count(), 2)

    def test_multiple_tags_all(self):
        value = f"{self.red.external_id},{self.blue.external_id}"
        result = TagFilter(behavior="all").filter(self.qs, value)
        self.assertEqual(list(result), [self.both_txn])

    def test_unknown_tag_id_matches_nothing(self):
        self.assertEqual(TagFilter().filter(self.qs, str(generate_external_id())).count(), 0)

    def test_malformed_id_matches_nothing(self):
        self.assertEqual(TagFilter().filter(self.qs, "not-a-uuid").count(), 0)

    def test_malformed_id_is_skipped_among_valid_ones(self):
        value = f"nope,{self.blue.external_id}"
        self.assertEqual(list(TagFilter().filter(self.qs, value)), [self.both_txn])

    def test_deleted_tag_matches_nothing(self):
        TagConfig.objects.filter(id=self.red.id).update(deleted=True)
        self.assertEqual(TagFilter().filter(self.qs, str(self.red.external_id)).count(), 0)


class TagConfigAPITests(NoetherAPITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.auditor = UserFactory()
        SecurityLedgerUser.objects.create(
            ledger=cls.ledger, user=cls.auditor, role=Role.objects.get(name="Auditor")
        )
        cls.bookkeeper = UserFactory()
        SecurityLedgerUser.objects.create(
            ledger=cls.ledger, user=cls.bookkeeper, role=Role.objects.get(name="Bookkeeper")
        )

    def url(self, suffix=""):
        return self.ledger_url(f"tag-configs/{suffix}")

    def create_tag(self, **payload):
        body = {"display": "root", "resource": "transaction"}
        body.update(payload)
        return self.client.post(self.url(), body, format="json")

    def test_create_list_retrieve_update_delete(self):
        response = self.create_tag(display="root", exclusive_children=True)
        self.assertEqual(response.status_code, 201, response.content)
        tag_id = response.json()["id"]
        self.assertTrue(response.json()["exclusive_children"])
        self.assertEqual(response.json()["parent"], {})

        child = self.create_tag(display="child", parent=tag_id)
        self.assertEqual(child.status_code, 201, child.content)
        self.assertEqual(child.json()["parent"]["display"], "root")
        self.assertEqual(child.json()["level_cache"], 1)

        listing = self.client.get(self.url())
        self.assertEqual(listing.json()["count"], 2)

        detail = self.client.get(self.url(f"{tag_id}/"))
        self.assertEqual(detail.json()["display"], "root")
        self.assertTrue(detail.json()["has_children"])

        patched = self.client.patch(self.url(f"{tag_id}/"), {"display": "renamed"}, format="json")
        self.assertEqual(patched.status_code, 200, patched.content)
        self.assertEqual(patched.json()["display"], "renamed")

        deleted = self.client.delete(self.url(f"{tag_id}/"))
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(self.url()).json()["count"], 1)

    def test_create_with_unknown_parent_rejected(self):
        response = self.create_tag(display="orphan", parent=str(generate_external_id()))
        self.assertEqual(response.status_code, 400)
        self.assertIn("unknown parent tag", response.json()["errors"][0]["msg"])

    def test_create_with_parent_resource_mismatch_rejected(self):
        parent = make_tag(self.ledger, "acct", resource="account")
        response = self.create_tag(display="child", parent=str(parent.external_id))
        self.assertEqual(response.status_code, 400)
        self.assertIn("resource mismatch", response.json()["errors"][0]["msg"])

    def test_create_with_invalid_resource_rejected(self):
        response = self.create_tag(display="x", resource="nonsense")
        self.assertEqual(response.status_code, 400)

    def test_create_missing_display_rejected(self):
        response = self.client.post(self.url(), {"resource": "transaction"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_cross_ledger_parent_rejected(self):
        foreign = make_tag(LedgerFactory(), "foreign")
        response = self.create_tag(display="child", parent=str(foreign.external_id))
        self.assertEqual(response.status_code, 400)
        self.assertIn("unknown parent tag", response.json()["errors"][0]["msg"])

    def test_viewer_denied_read_and_write(self):
        self.client.force_authenticate(self.viewer)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.create_tag().status_code, 403)

    def test_auditor_can_read_but_not_write(self):
        tag = make_tag(self.ledger, "readable")
        self.client.force_authenticate(self.auditor)
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        self.assertEqual(self.client.get(self.url(f"{tag.external_id}/")).status_code, 200)
        self.assertEqual(self.create_tag().status_code, 403)
        self.assertEqual(
            self.client.patch(
                self.url(f"{tag.external_id}/"), {"display": "x"}, format="json"
            ).status_code,
            403,
        )
        self.assertEqual(self.client.delete(self.url(f"{tag.external_id}/")).status_code, 403)

    def test_bookkeeper_can_write(self):
        self.client.force_authenticate(self.bookkeeper)
        self.assertEqual(self.create_tag().status_code, 201)


class TransactionTaggingAPITests(NoetherAPITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.auditor = UserFactory()
        SecurityLedgerUser.objects.create(
            ledger=cls.ledger, user=cls.auditor, role=Role.objects.get(name="Auditor")
        )
        cls.bookkeeper = UserFactory()
        SecurityLedgerUser.objects.create(
            ledger=cls.ledger, user=cls.bookkeeper, role=Role.objects.get(name="Bookkeeper")
        )

    def setUp(self):
        super().setUp()
        self.tag = make_tag(self.ledger, "alpha")
        self.other = make_tag(self.ledger, "beta")

    def txn_url(self, txn_id, suffix=""):
        return self.ledger_url(f"transactions/{txn_id}/{suffix}")

    def test_set_and_unset_tag_on_draft(self):
        txn = self.create_txn()
        response = self.client.post(
            self.txn_url(txn["id"], "set-tag/"),
            {"tags": [str(self.tag.external_id)]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([t["display"] for t in response.json()["tags"]], ["alpha"])

        response = self.client.post(
            self.txn_url(txn["id"], "unset-tag/"),
            {"tags": [str(self.tag.external_id)]},
            format="json",
        )
        self.assertEqual(response.json()["tags"], [])

    def test_tags_settable_on_posted_transaction(self):
        """ADR-0001 immutability does not cover tags: they are metadata."""
        txn = self.create_txn(post=True)
        self.assertEqual(txn["status"], "posted")
        response = self.client.post(
            self.txn_url(txn["id"], "set-tag/"),
            {"tags": [str(self.tag.external_id)]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([t["display"] for t in response.json()["tags"]], ["alpha"])
        unset = self.client.post(
            self.txn_url(txn["id"], "unset-tag/"),
            {"tags": [str(self.tag.external_id)]},
            format="json",
        )
        self.assertEqual(unset.status_code, 200, unset.content)
        self.assertEqual(unset.json()["tags"], [])

    def test_set_multiple_tags(self):
        txn = self.create_txn()
        response = self.client.post(
            self.txn_url(txn["id"], "set-tag/"),
            {"tags": [str(self.tag.external_id), str(self.other.external_id)]},
            format="json",
        )
        self.assertEqual(len(response.json()["tags"]), 2)

    def test_unset_tag_not_applied_returns_400(self):
        txn = self.create_txn()
        response = self.client.post(
            self.txn_url(txn["id"], "unset-tag/"),
            {"tags": [str(self.tag.external_id)]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("is not applied", response.json()["errors"][0]["msg"])

    def test_invalid_tag_request_body_returns_400(self):
        txn = self.create_txn()
        response = self.client.post(
            self.txn_url(txn["id"], "set-tag/"), {"tags": "nope"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_auditor_denied_tag_apply(self):
        txn = self.create_txn()
        self.client.force_authenticate(self.auditor)
        response = self.client.post(
            self.txn_url(txn["id"], "set-tag/"),
            {"tags": [str(self.tag.external_id)]},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_viewer_denied_tag_apply(self):
        txn = self.create_txn()
        self.client.force_authenticate(self.viewer)
        response = self.client.post(
            self.txn_url(txn["id"], "set-tag/"),
            {"tags": [str(self.tag.external_id)]},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_bookkeeper_allowed_tag_apply(self):
        txn = self.create_txn()
        self.client.force_authenticate(self.bookkeeper)
        response = self.client.post(
            self.txn_url(txn["id"], "set-tag/"),
            {"tags": [str(self.tag.external_id)]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)

    def test_cross_ledger_isolation_on_apply(self):
        foreign_tag = make_tag(LedgerFactory(), "foreign")
        txn = self.create_txn()
        response = self.client.post(
            self.txn_url(txn["id"], "set-tag/"),
            {"tags": [str(foreign_tag.external_id)]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("unknown tag", response.json()["errors"][0]["msg"])

    def test_exclusivity_enforced_over_rest(self):
        parent = make_tag(self.ledger, "colour", exclusive_children=True)
        red = make_tag(self.ledger, "red", parent=parent)
        blue = make_tag(self.ledger, "blue", parent=parent)
        txn = self.create_txn()
        self.client.post(
            self.txn_url(txn["id"], "set-tag/"),
            {"tags": [str(red.external_id)]},
            format="json",
        )
        response = self.client.post(
            self.txn_url(txn["id"], "set-tag/"),
            {"tags": [str(blue.external_id)]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("allows only one tag", response.json()["errors"][0]["msg"])

    def test_list_filtering_by_tag(self):
        tagged = self.create_txn()
        self.create_txn()
        self.client.post(
            self.txn_url(tagged["id"], "set-tag/"),
            {"tags": [str(self.tag.external_id)]},
            format="json",
        )
        listing = self.client.get(
            self.ledger_url("transactions/"), {"tags": str(self.tag.external_id)}
        )
        self.assertEqual(listing.json()["count"], 1)
        self.assertEqual(listing.json()["results"][0]["id"], tagged["id"])

        empty = self.client.get(
            self.ledger_url("transactions/"), {"tags": str(self.other.external_id)}
        )
        self.assertEqual(empty.json()["count"], 0)
