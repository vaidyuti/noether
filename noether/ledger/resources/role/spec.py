"""Role serialization. Roles are code-defined (RoleController), not DB rows,
so the spec is a plain serializer function rather than a NoetherResource."""


def serialize_role(role):
    return {
        "name": role.name,
        "description": role.description,
        "permissions": list(role.permissions),
    }
