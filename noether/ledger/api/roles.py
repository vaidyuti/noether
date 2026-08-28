from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from noether.ledger.resources.role.spec import serialize_role
from noether.security.roles.role import RoleController


class RoleViewSet(ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        return Response({"results": [serialize_role(role) for role in RoleController.get_roles()]})
