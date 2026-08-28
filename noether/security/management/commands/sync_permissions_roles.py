from django.core.management.base import BaseCommand
from django.db import transaction

from noether.security.models import Permission, Role, RolePermission
from noether.security.permissions.base import PermissionController
from noether.security.roles.role import RoleController


def sync_permissions_roles() -> None:
    permissions = PermissionController.get_permissions()
    permission_rows = {}
    for slug, meta in permissions.items():
        row, _ = Permission.objects.update_or_create(
            slug=slug, defaults={"name": meta.name, "description": meta.description}
        )
        permission_rows[slug] = row
    for role in RoleController.get_roles():
        role_row, _ = Role.objects.update_or_create(
            name=role.name, defaults={"description": role.description, "is_system": True}
        )
        for slug in role.permissions:
            RolePermission.objects.get_or_create(role=role_row, permission=permission_rows[slug])
        RolePermission.objects.filter(role=role_row).exclude(
            permission__slug__in=role.permissions
        ).delete()


class Command(BaseCommand):
    help = "Sync code-defined permissions and roles into the database"

    def handle(self, *args, **options):
        with transaction.atomic():
            sync_permissions_roles()
        self.stdout.write("Synced permissions and roles")
