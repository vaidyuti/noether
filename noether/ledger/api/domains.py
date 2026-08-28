from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from noether.domains.config import DomainConfigError
from noether.domains.registry import DomainRegistry
from noether.ledger.resources.domain.spec import serialize_domain


class DomainViewSet(ViewSet):
    permission_classes = [IsAuthenticated]
    lookup_field = "slug"

    def list(self, request):
        return Response({"results": [serialize_domain(c) for c in DomainRegistry.all()]})

    def retrieve(self, request, slug=None):
        try:
            config = DomainRegistry.get(slug)
        except DomainConfigError:
            return Response(
                {"errors": [{"type": "object_not_found", "msg": "Domain not found"}]},
                status=404,
            )
        return Response(serialize_domain(config, detail=True))
