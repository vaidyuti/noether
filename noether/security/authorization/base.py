class PermissionDeniedError(Exception):
    pass


class AuthorizationHandler:
    """Base class for authorization handlers.

    Handlers expose ``can_<action>`` methods with signature
    ``(user, ledger, obj=None)`` returning booleans.
    """

    def check_permission_in_ledger(self, permission_slug, user, ledger) -> bool:
        from noether.security.models import LedgerUser, RolePermission

        if user.is_superuser:
            return True
        membership = LedgerUser.objects.filter(ledger=ledger, user=user).first()
        if membership is None:
            return False
        return RolePermission.objects.filter(
            role=membership.role, permission__slug=permission_slug
        ).exists()


class LedgerAccessHandler(AuthorizationHandler):
    def can_access_ledger(self, user, ledger, permission_slug):
        return self.check_permission_in_ledger(permission_slug, user, ledger)

    def get_accessible_ledgers(self, user):
        from noether.ledger.models import Ledger

        queryset = Ledger.objects.filter(deleted=False)
        if user.is_superuser:
            return queryset
        return queryset.filter(memberships__user=user)


class TagConfigAccessHandler(AuthorizationHandler):
    def can_apply_tag_config(self, user, ledger, tag_config):
        from noether.security.permissions.base import TagPermissions

        del tag_config
        return self.check_permission_in_ledger(TagPermissions.tag__apply.name, user, ledger)


class AuthorizationController:
    override_authz_controllers: list = []
    internal_controllers: list = [LedgerAccessHandler, TagConfigAccessHandler]

    cache = {}

    @classmethod
    def build_cache(cls):
        cls.cache = {}
        controllers = cls.override_authz_controllers + cls.internal_controllers
        for controller in controllers:
            for method_name in dir(controller):
                is_hook = method_name.startswith(("can_", "get_"))
                if is_hook and method_name not in cls.cache:
                    cls.cache[method_name] = controller

    @classmethod
    def call(cls, method_name, *args, **kwargs):
        if not cls.cache:
            cls.build_cache()
        if method_name not in cls.cache:
            raise PermissionDeniedError(f"no authorization handler for {method_name!r}")
        controller = cls.cache[method_name]()
        return getattr(controller, method_name)(*args, **kwargs)

    @classmethod
    def register_internal_controller(cls, controller) -> None:
        if controller not in cls.internal_controllers:
            cls.internal_controllers.append(controller)
        cls.cache = {}

    @classmethod
    def register_override_controller(cls, controller) -> None:
        if controller not in cls.override_authz_controllers:
            cls.override_authz_controllers.append(controller)
        cls.cache = {}
