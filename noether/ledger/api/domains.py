from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from noether.domains.config import DomainConfigError
from noether.domains.registry import DomainRegistry


def _serialize_domain(config, detail=False):
    data = {"slug": config.slug, "name": config.name, "version": config.version}
    if detail:
        data["account_types"] = [
            {"name": t.name, "normal_balance": t.normal_balance} for t in config.account_types
        ]
        data["default_units"] = [
            {"symbol": u.symbol, "name": u.name, "precision": u.precision}
            for u in config.default_units
        ]
        data["chart_templates"] = [
            {
                "name": template.name,
                "nodes": [
                    {
                        "path": node.path,
                        "account_type": node.account_type,
                        "unit": node.unit,
                        "placeholder": node.placeholder,
                    }
                    for node in template.nodes
                ],
            }
            for template in config.chart_templates
        ]
    return data


class DomainViewSet(ViewSet):
    permission_classes = [IsAuthenticated]
    lookup_field = "slug"

    def list(self, request):
        return Response({"results": [_serialize_domain(c) for c in DomainRegistry.all()]})

    def retrieve(self, request, slug=None):
        try:
            config = DomainRegistry.get(slug)
        except DomainConfigError:
            return Response(
                {"errors": [{"type": "object_not_found", "msg": "Domain not found"}]},
                status=404,
            )
        return Response(_serialize_domain(config, detail=True))
