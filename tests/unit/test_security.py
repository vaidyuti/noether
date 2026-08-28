from django.core.management import call_command
from django.test import TestCase

from noether.ledger.tests.factories import LedgerFactory, UserFactory
from noether.security.authorization.base import (
    AuthorizationController,
    AuthorizationHandler,
    LedgerAccessHandler,
    PermissionDeniedError,
)
from noether.security.models import LedgerUser, Permission, Role, RolePermission
from noether.security.permissions.base import LedgerPermissions, PermissionController
from noether.security.roles.role import OWNER_ROLE, VIEWER_ROLE, RoleController
from noether.security.roles.role import Role as RoleDef


class SyncCommandTests(TestCase):
    def test_sync_creates_permissions_and_roles(self):
        call_command("sync_permissions_roles")
        self.assertTrue(Permission.objects.filter(slug="ledger__read").exists())
        owner = Role.objects.get(name="Owner")
        self.assertEqual(
            RolePermission.objects.filter(role=owner).count(), len(OWNER_ROLE.permissions)
        )
        viewer = Role.objects.get(name="Viewer")
        self.assertEqual(
            set(
                RolePermission.objects.filter(role=viewer).values_list(
                    "permission__slug", flat=True
                )
            ),
            set(VIEWER_ROLE.permissions),
        )

    def test_sync_is_idempotent(self):
        call_command("sync_permissions_roles")
        before = RolePermission.objects.count()
        call_command("sync_permissions_roles")
        self.assertEqual(RolePermission.objects.count(), before)

    def test_sync_prunes_removed_role_permissions(self):
        call_command("sync_permissions_roles")
        viewer = Role.objects.get(name="Viewer")
        extra = Permission.objects.get(slug="transaction__post")
        RolePermission.objects.create(role=viewer, permission=extra)
        call_command("sync_permissions_roles")
        self.assertFalse(RolePermission.objects.filter(role=viewer, permission=extra).exists())


class RoleControllerTests(TestCase):
    def test_plug_role_registration(self):
        agent = RoleDef(name="CoreTestOnlyRole", description="x", permissions=("transaction__post",))
        RoleController.register_role(agent)
        try:
            self.assertIn(agent, RoleController.get_roles())
            RoleController.register_role(agent)  # idempotent
            self.assertEqual(RoleController.get_roles().count(agent), 1)
            self.assertIs(RoleController.get_role_by_name("CoreTestOnlyRole"), agent)
        finally:
            RoleController.override_roles.remove(agent)

    def test_get_role_by_name_unknown(self):
        self.assertIsNone(RoleController.get_role_by_name("Nobody"))


class PermissionControllerTests(TestCase):
    def test_has_permission(self):
        self.assertTrue(PermissionController.has_permission("ledger__read"))
        self.assertFalse(PermissionController.has_permission("bogus__perm"))

    def test_register_permission_handler(self):
        import enum

        from noether.security.permissions.base import PermissionMeta

        class ExtraPermissions(enum.Enum):
            widget__read = PermissionMeta("Read widget", "Can read widgets")

        PermissionController.register_permission_handler(ExtraPermissions)
        try:
            self.assertTrue(PermissionController.has_permission("widget__read"))
            PermissionController.register_permission_handler(ExtraPermissions)
            self.assertEqual(
                PermissionController.override_permission_handlers.count(ExtraPermissions), 1
            )
        finally:
            PermissionController.override_permission_handlers.remove(ExtraPermissions)
            PermissionController.cache = {}


class AuthorizationControllerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("sync_permissions_roles")
        cls.owner_role = Role.objects.get(name="Owner")
        cls.viewer_role = Role.objects.get(name="Viewer")
        cls.owner = UserFactory()
        cls.viewer = UserFactory()
        cls.outsider = UserFactory()
        cls.superuser = UserFactory(username="admin-super")
        cls.superuser.is_superuser = True
        cls.superuser.save()
        cls.ledger = LedgerFactory()
        LedgerUser.objects.create(ledger=cls.ledger, user=cls.owner, role=cls.owner_role)
        LedgerUser.objects.create(ledger=cls.ledger, user=cls.viewer, role=cls.viewer_role)

    def setUp(self):
        AuthorizationController.cache = {}

    def test_owner_can_post(self):
        self.assertTrue(
            AuthorizationController.call(
                "can_access_ledger", self.owner, self.ledger, "transaction__post"
            )
        )

    def test_viewer_cannot_post(self):
        self.assertFalse(
            AuthorizationController.call(
                "can_access_ledger", self.viewer, self.ledger, "transaction__post"
            )
        )

    def test_viewer_can_read_balance(self):
        self.assertTrue(
            AuthorizationController.call(
                "can_access_ledger", self.viewer, self.ledger, "balance__read"
            )
        )

    def test_outsider_denied(self):
        self.assertFalse(
            AuthorizationController.call(
                "can_access_ledger", self.outsider, self.ledger, "ledger__read"
            )
        )

    def test_superuser_bypasses(self):
        self.assertTrue(
            AuthorizationController.call(
                "can_access_ledger", self.superuser, self.ledger, "transaction__post"
            )
        )

    def test_accessible_ledgers_filtering(self):
        other = LedgerFactory()
        accessible = AuthorizationController.call("get_accessible_ledgers", self.owner)
        self.assertIn(self.ledger, accessible)
        self.assertNotIn(other, accessible)

    def test_accessible_ledgers_superuser_sees_all(self):
        other = LedgerFactory()
        accessible = AuthorizationController.call("get_accessible_ledgers", self.superuser)
        self.assertIn(other, accessible)

    def test_unknown_method_raises(self):
        with self.assertRaises(PermissionDeniedError):
            AuthorizationController.call("can_fly", self.owner)

    def test_override_controller_wins(self):
        class DenyAll(AuthorizationHandler):
            def can_access_ledger(self, user, ledger, permission_slug):
                return False

        AuthorizationController.register_override_controller(DenyAll)
        try:
            AuthorizationController.register_override_controller(DenyAll)  # idempotent
            self.assertFalse(
                AuthorizationController.call(
                    "can_access_ledger", self.owner, self.ledger, "ledger__read"
                )
            )
        finally:
            AuthorizationController.override_authz_controllers.remove(DenyAll)
            AuthorizationController.cache = {}

    def test_register_internal_controller(self):
        class ExtraHandler(AuthorizationHandler):
            def can_extra(self, user):
                return True

        AuthorizationController.register_internal_controller(ExtraHandler)
        try:
            AuthorizationController.register_internal_controller(ExtraHandler)
            self.assertEqual(AuthorizationController.internal_controllers.count(ExtraHandler), 1)
            self.assertTrue(AuthorizationController.call("can_extra", self.owner))
        finally:
            AuthorizationController.internal_controllers.remove(ExtraHandler)
            AuthorizationController.cache = {}

    def test_ledger_access_handler_direct(self):
        handler = LedgerAccessHandler()
        self.assertTrue(
            handler.can_access_ledger(self.owner, self.ledger, LedgerPermissions.ledger__read.name)
        )
