"""pydantic mixins wiring extensions into resource specs.

Write side: :class:`ExtensionValidator` validates every key of the incoming
``extensions`` mapping through its registered handler. Unknown keys are
**rejected** — a payload naming an extension nobody declared is a client bug or
a stale deployment, and silently dropping it would lose data without telling
anyone (see ADR-0012).

Read side: the renderer mixins merge every registered handler's rendered data
into the serialized mapping, so responses always describe the full declared
extension surface.
"""

from pydantic import field_validator

from noether.extensions.registry import ExtensionRegistry


def validate_extensions(data, resource_type):
    if not isinstance(data, dict):
        raise ValueError("extensions must be an object")
    cleaned = {}
    for key, value in data.items():
        handler = ExtensionRegistry.get_extension_obj(resource_type, key)
        if handler is None:
            raise ValueError(f"unknown extension {key!r} for resource {resource_type!r}")
        handler.validate(value)
        cleaned[key] = handler.serialize_extensions(value)
    return cleaned


class ExtensionValidator:
    """Mixin for create/update specs. Requires ``__extension_resource__``."""

    extensions: dict = {}

    @field_validator("extensions")
    @classmethod
    def _validate_extensions(cls, value):
        return validate_extensions(value, cls.__extension_resource__.value)


class ExtensionListRenderer:
    """Mixin for read specs: renders every registered extension."""

    extensions: dict = {}

    @classmethod
    def render_extension(cls, handler, data, obj):
        return handler.deserialize_extensions_list(data, obj)

    @classmethod
    def perform_extra_serialization(cls, mapping, obj, *args, **kwargs):
        resource_type = cls.__extension_resource__.value
        stored = obj.extensions or {}
        rendered = {}
        for key, handler in ExtensionRegistry.get_extensions_for_resource(resource_type).items():
            rendered[key] = cls.render_extension(handler, stored.get(key, {}), obj)
        mapping["extensions"] = rendered
        return super().perform_extra_serialization(mapping, obj, *args, **kwargs)


class ExtensionRetrieveRenderer(ExtensionListRenderer):
    """Mixin for retrieve specs: renders using the retrieve hook."""

    @classmethod
    def render_extension(cls, handler, data, obj):
        return handler.deserialize_extensions_retrieve(data, obj)
