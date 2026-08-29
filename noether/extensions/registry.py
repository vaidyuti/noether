"""Registry of extension handlers, keyed by resource type and extension name."""


class ExtensionRegistry:
    """Process-wide registry of extension handlers.

    Registration is idempotent for identical handlers (ADR-0011 style): Django
    may call ``AppConfig.ready()`` more than once, so re-registering the same
    extension name for a resource with an equivalent handler is a no-op.
    Registering a *different* handler under a name already taken is an error.
    """

    _extensions: dict[str, dict[str, object]] = {}

    @classmethod
    def register(cls, extension_obj) -> None:
        from noether.extensions.base import ExtensionBase

        if not isinstance(extension_obj, ExtensionBase):
            raise ValueError("extension must be an instance of ExtensionBase")
        if not extension_obj.resource_type or not extension_obj.extension_name:
            raise ValueError("extension requires both resource_type and extension_name")
        resource = extension_obj.resource_type.value
        bucket = cls._extensions.setdefault(resource, {})
        existing = bucket.get(extension_obj.extension_name)
        if existing is not None:
            if cls._is_equivalent(existing, extension_obj):
                return
            raise ValueError(
                f"extension {extension_obj.extension_name!r} is already registered "
                f"for resource {resource!r} with a different handler"
            )
        bucket[extension_obj.extension_name] = extension_obj

    @staticmethod
    def _is_equivalent(existing, candidate) -> bool:
        if type(existing) is not type(candidate):
            return False
        return existing.extension_version == candidate.extension_version

    @classmethod
    def get_extension_obj(cls, resource_type, extension_name):
        return cls._extensions.get(resource_type, {}).get(extension_name)

    @classmethod
    def get_extensions(cls):
        return cls._extensions

    @classmethod
    def get_extensions_for_resource(cls, resource_type):
        return cls._extensions.get(resource_type, {})
