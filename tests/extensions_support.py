"""A plug-style extension used only by the test-suite."""

from noether.extensions.base import ExtensionResource, PlugExtension
from noether.extensions.registry import ExtensionRegistry


class DemoAccountExtension(PlugExtension):
    resource_type = ExtensionResource.account
    extension_name = "demo"
    extension_version = "1.0.0"
    write_schema = {
        "type": "object",
        "properties": {"label": {"type": "string"}},
        "additionalProperties": False,
    }

    def validate(self, data, resource=None):
        super().validate(data, resource)
        if data.get("label", "").strip() == "forbidden":
            raise ValueError("label 'forbidden' is not allowed")
        return data

    def serialize_extensions(self, data, resource=None):
        if "label" in data:
            return {**data, "label": data["label"].strip()}
        return data

    def deserialize_extensions_list(self, data, resource):
        return {**data, "rendered": "list"}

    def deserialize_extensions_retrieve(self, data, resource):
        return {**data, "rendered": "retrieve"}


def ensure_demo_registered() -> None:
    ExtensionRegistry.register(DemoAccountExtension())


ensure_demo_registered()
