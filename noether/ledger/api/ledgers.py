from rest_framework.exceptions import ValidationError

from noether.api.viewsets.base import NoetherModelViewSet
from noether.domains.config import DomainConfigError
from noether.domains.services import create_ledger
from noether.ledger.models import Ledger
from noether.ledger.resources.ledger.spec import (
    LedgerCreateSpec,
    LedgerReadSpec,
    LedgerRetrieveSpec,
    LedgerUpdateSpec,
)
from noether.security.authorization.base import AuthorizationController, PermissionDeniedError
from noether.security.permissions.base import LedgerPermissions


class LedgerViewSet(NoetherModelViewSet):
    database_model = Ledger
    pydantic_model = LedgerCreateSpec
    pydantic_read_model = LedgerReadSpec
    pydantic_update_model = LedgerUpdateSpec
    pydantic_retrieve_model = LedgerRetrieveSpec

    def get_queryset(self):
        return (
            AuthorizationController.call("get_accessible_ledgers", self.request.user)
            .select_related("domain")
            .order_by("-id")
        )

    def handle_create(self, request_data, external_id=None):
        clean_data = self.clean_create_data(request_data)
        instance = self.pydantic_model.model_validate(clean_data)
        instance._context = {"is_create": True}
        self.authorize_create(instance)
        try:
            ledger = create_ledger(
                domain_slug=instance.domain,
                name=instance.name,
                owner=self.request.user,
                chart_template=instance.chart_template,
                description=instance.description,
                slug=instance.slug,
                external_id=external_id,
            )
        except DomainConfigError as exc:
            raise ValidationError(str(exc)) from exc
        ledger.settings = instance.settings
        ledger.extensions = instance.extensions
        ledger.save(update_fields=["settings", "extensions", "modified_date"])
        return self.get_retrieve_pydantic_model().serialize(ledger).to_json()

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
