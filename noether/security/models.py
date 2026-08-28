from django.db import models

from noether.ledger.models_base import NoetherBaseModel


class Permission(NoetherBaseModel):
    slug = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")


class Role(NoetherBaseModel):
    name = models.CharField(max_length=64, unique=True)
    description = models.TextField(blank=True, default="")
    is_system = models.BooleanField(default=True)


class RolePermission(NoetherBaseModel):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="roles")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="unique_role_permission"),
        ]


class LedgerUser(NoetherBaseModel):
    ledger = models.ForeignKey(
        "ledger.Ledger", on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey("users.User", on_delete=models.CASCADE, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["ledger", "user"], name="unique_ledger_user"),
        ]
