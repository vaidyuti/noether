from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from noether.security.roles.role import RoleController


class RoleViewSet(ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        return Response(
            {
                "results": [
                    {
                        "name": role.name,
                        "description": role.description,
                        "permissions": list(role.permissions),
                    }
                    for role in RoleController.get_roles()
                ]
            }
        )
