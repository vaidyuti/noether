"""Extension handler base classes.

An *extension* is a namespaced blob of JSON stored on a core model's
``extensions`` field, whose allowed shape is declared out-of-band — either by
the deployment (environment variable) or by a plug (code). Handlers validate
that blob on write and render it on read.
"""

import json
from enum import StrEnum
from os import getenv

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as jsonschema_validate

from noether.extensions.registry import ExtensionRegistry


class ExtensionResource(StrEnum):
    transaction = "transaction"
    account = "account"
    ledger = "ledger"


class ExtensionOwner(StrEnum):
    core = "core"
    plug = "plug"


class ExtensionBase:
    """Hook surface for one named extension on one resource type."""

    resource_type: ExtensionResource | None = None
    extension_name: str = ""
    extension_version: str = ""
    extension_owner: ExtensionOwner = ExtensionOwner.core

    write_schema: dict = {}
    read_schema: dict = {}
    retrieve_schema: dict = {}

    def get_write_schema(self) -> dict:
        return self.write_schema

    def get_read_schema(self) -> dict:
        return self.read_schema or self.get_write_schema()

    def get_retrieve_schema(self) -> dict:
        return self.retrieve_schema or self.get_read_schema()

    def validate(self, data, resource=None):
        """Raise ``ValueError`` when ``data`` does not fit the write schema."""
        schema = self.get_write_schema()
        if not schema:
            return data
        try:
            jsonschema_validate(data, schema)
        except JsonSchemaValidationError as exc:
            raise ValueError(
                f"extension {self.extension_name!r} payload is invalid: {exc.message}"
            ) from exc
        return data

    def serialize_extensions(self, data, resource=None):
        """Normalize validated write data before it is persisted."""
        return data

    def deserialize_extensions_list(self, data, resource):
        """Render stored data for list responses."""
        return data

    def deserialize_extensions_retrieve(self, data, resource):
        """Render stored data for retrieve responses."""
        return self.deserialize_extensions_list(data, resource)


class EnvExtension(ExtensionBase):
    """Deployment-declared extension; schemas come from the environment.

    Keys are ``NOETHER_EXTENSIONS_<RESOURCE>_<WRITE|READ|RETRIEVE>`` and hold a
    JSON Schema document as a JSON string. ``READ`` falls back to ``WRITE`` and
    ``RETRIEVE`` falls back to ``READ``.
    """

    extension_name = "core"
    extension_version = "1.0.0"
    extension_owner = ExtensionOwner.core

    def __init__(self, resource_type: ExtensionResource):
        self.resource_type = resource_type

    def schema_key(self, action: str) -> str:
        return f"NOETHER_EXTENSIONS_{self.resource_type.value.upper()}_{action}"

    def get_env_schema(self, action: str) -> dict:
        raw = getenv(self.schema_key(action))
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{self.schema_key(action)} is not valid JSON") from exc

    def get_write_schema(self) -> dict:
        return self.get_env_schema("WRITE")

    def get_read_schema(self) -> dict:
        return self.get_env_schema("READ") or self.get_write_schema()

    def get_retrieve_schema(self) -> dict:
        return self.get_env_schema("RETRIEVE") or self.get_read_schema()


class PlugExtension(ExtensionBase):
    """Code-declared extension registered by a plug in ``AppConfig.ready()``."""

    extension_owner = ExtensionOwner.plug


for _resource in ExtensionResource:
    ExtensionRegistry.register(EnvExtension(_resource))
