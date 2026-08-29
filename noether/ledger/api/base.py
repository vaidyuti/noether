from django.http import Http404

from noether.ledger.models_base import slug_or_uuid_filters
from noether.security.authorization.base import AuthorizationController, PermissionDeniedError


class LedgerScopedMixin:
    """Resolves the ledger from the nested route with 404 on inaccessible ledgers."""

    def get_ledger(self):
        if not hasattr(self, "_ledger"):
            from noether.ledger.models import Ledger

            queryset = AuthorizationController.call("get_accessible_ledgers", self.request.user)
            filters = slug_or_uuid_filters(Ledger, self.kwargs["ledger_external_id"])
            try:
                self._ledger = queryset.get(**filters)
            except Exception as exc:
                raise Http404 from exc
        return self._ledger

    def check_ledger_permission(self, permission_slug):
        allowed = AuthorizationController.call(
            "can_access_ledger", self.request.user, self.get_ledger(), permission_slug
        )
        if not allowed:
            raise PermissionDeniedError(f"missing permission {permission_slug}")
