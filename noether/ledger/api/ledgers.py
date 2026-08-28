from noether.api.viewsets.base import NoetherModelViewSet
from noether.domains.config import DomainConfigError
from noether.domains.registry import DomainRegistry
from noether.domains.services import instantiate_chart
from noether.ledger.models import Domain, Ledger
from noether.ledger.resources.ledger.spec import (
    LedgerCreateSpec,
    LedgerReadSpec,
    LedgerUpdateSpec,
)
from noether.security.authorization.base import AuthorizationController, PermissionDeniedError
from noether.security.models import LedgerUser
from noether.security.models import Role as RoleModel
from noether.security.permissions.base import LedgerPermissions
from noether.security.roles.role import OWNER_ROLE


class LedgerViewSet(NoetherModelViewSet):
    database_model = Ledger
    pydantic_model = LedgerCreateSpec
    pydantic_read_model = LedgerReadSpec
    pydantic_update_model = LedgerUpdateSpec

    def get_queryset(self):
        return (
            AuthorizationController.call("get_accessible_ledgers", self.request.user)
            .select_related("domain")
            .order_by("-id")
        )

    def validate_data(self, instance, model_obj=None):
        if model_obj is not None:
            return
        try:
            config = DomainRegistry.get(instance.domain)
        except DomainConfigError as exc:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(str(exc)) from exc
        instance._domain_row = Domain.objects.filter(slug=instance.domain).first()
        if instance._domain_row is None:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(f"domain {instance.domain!r} is not synced")
        if instance.chart_template is not None:
            names = [t.name for t in config.chart_templates]
            if instance.chart_template not in names:
                from rest_framework.exceptions import ValidationError

                raise ValidationError(f"unknown chart template {instance.chart_template!r}")

    def perform_create(self, instance):
        super().perform_create(instance)
        spec = getattr(instance, "_spec", None)
        config = DomainRegistry.get(instance.domain.slug)
        chart_template_name = spec.chart_template if spec else None
        if chart_template_name is not None:
            template = next(t for t in config.chart_templates if t.name == chart_template_name)
            instantiate_chart(ledger=instance, config=config, template=template)
        owner_role = RoleModel.objects.get(name=OWNER_ROLE.name)
        LedgerUser.objects.create(ledger=instance, user=self.request.user, role=owner_role)

    def handle_create(self, request_data):
        clean_data = self.clean_create_data(request_data)
        instance = self.pydantic_model.model_validate(clean_data)
        instance._context = {"is_create": True}
        self.validate_data(instance, None)
        self.authorize_create(instance)
        model_instance = instance.de_serialize()
        model_instance._spec = instance
        self.perform_create(model_instance)
        return self.get_retrieve_pydantic_model().serialize(model_instance).to_json()

    def _check(self, permission):
        instance = self.get_object()
        allowed = AuthorizationController.call(
            "can_access_ledger", self.request.user, instance, permission
        )
        if not allowed:
            raise PermissionDeniedError(f"missing permission {permission}")

    def authorize_update(self, request_obj, model_instance):
        self._check(LedgerPermissions.ledger__write.name)

    def authorize_destroy(self, instance):
        self._check(LedgerPermissions.ledger__delete.name)
