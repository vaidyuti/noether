import json
import os
from unittest import mock

from django.test import SimpleTestCase

from noether.extensions.base import (
    EnvExtension,
    ExtensionBase,
    ExtensionOwner,
    ExtensionResource,
    PlugExtension,
)
from noether.extensions.registry import ExtensionRegistry
from noether.extensions.validator import validate_extensions
from tests.extensions_support import DemoAccountExtension, ensure_demo_registered

WRITE_KEY = "NOETHER_EXTENSIONS_LEDGER_WRITE"
READ_KEY = "NOETHER_EXTENSIONS_LEDGER_READ"
RETRIEVE_KEY = "NOETHER_EXTENSIONS_LEDGER_RETRIEVE"

SCHEMA = {
    "type": "object",
    "properties": {"cost_centre": {"type": "string"}},
    "additionalProperties": False,
}


class EnvExtensionTests(SimpleTestCase):
    def setUp(self):
        self.ext = EnvExtension(ExtensionResource.ledger)

    def test_schema_key(self):
        self.assertEqual(self.ext.schema_key("WRITE"), WRITE_KEY)

    def test_absent_env_yields_empty_schemas(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.ext.get_write_schema(), {})
            self.assertEqual(self.ext.get_read_schema(), {})
            self.assertEqual(self.ext.get_retrieve_schema(), {})

    def test_absent_schema_accepts_anything(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.ext.validate({"anything": 1}), {"anything": 1})

    def test_invalid_json_raises(self):
        with (
            mock.patch.dict(os.environ, {WRITE_KEY: "{not json"}, clear=True),
            self.assertRaises(ValueError) as ctx,
        ):
            self.ext.get_write_schema()
        self.assertIn(WRITE_KEY, str(ctx.exception))

    def test_valid_schema_accepts_and_rejects(self):
        with mock.patch.dict(os.environ, {WRITE_KEY: json.dumps(SCHEMA)}, clear=True):
            self.assertEqual(self.ext.validate({"cost_centre": "x"}), {"cost_centre": "x"})
            with self.assertRaises(ValueError):
                self.ext.validate({"cost_centre": 5})

    def test_read_falls_back_to_write_and_retrieve_to_read(self):
        with mock.patch.dict(os.environ, {WRITE_KEY: json.dumps(SCHEMA)}, clear=True):
            self.assertEqual(self.ext.get_read_schema(), SCHEMA)
            self.assertEqual(self.ext.get_retrieve_schema(), SCHEMA)

    def test_explicit_read_and_retrieve_schemas_win(self):
        read = {"type": "object", "title": "read"}
        retrieve = {"type": "object", "title": "retrieve"}
        env = {
            WRITE_KEY: json.dumps(SCHEMA),
            READ_KEY: json.dumps(read),
            RETRIEVE_KEY: json.dumps(retrieve),
        }
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(self.ext.get_read_schema(), read)
            self.assertEqual(self.ext.get_retrieve_schema(), retrieve)

    def test_retrieve_falls_back_to_explicit_read(self):
        read = {"type": "object", "title": "read"}
        with mock.patch.dict(os.environ, {READ_KEY: json.dumps(read)}, clear=True):
            self.assertEqual(self.ext.get_retrieve_schema(), read)

    def test_render_hooks_are_identity(self):
        self.assertEqual(self.ext.deserialize_extensions_list({"a": 1}, None), {"a": 1})
        self.assertEqual(self.ext.deserialize_extensions_retrieve({"a": 1}, None), {"a": 1})
        self.assertEqual(self.ext.serialize_extensions({"a": 1}), {"a": 1})
        self.assertIs(self.ext.extension_owner, ExtensionOwner.core)


class ExtensionBaseTests(SimpleTestCase):
    def test_class_level_schema_fallbacks(self):
        class Ext(ExtensionBase):
            resource_type = ExtensionResource.account
            extension_name = "base_demo"
            write_schema = {"type": "object"}

        ext = Ext()
        self.assertEqual(ext.get_write_schema(), {"type": "object"})
        self.assertEqual(ext.get_read_schema(), {"type": "object"})
        self.assertEqual(ext.get_retrieve_schema(), {"type": "object"})

    def test_explicit_read_schema_used_for_retrieve(self):
        class Ext(ExtensionBase):
            read_schema = {"type": "object", "title": "r"}

        self.assertEqual(Ext().get_retrieve_schema(), {"type": "object", "title": "r"})


class RegistryTests(SimpleTestCase):
    def test_rejects_non_extension(self):
        with self.assertRaises(ValueError):
            ExtensionRegistry.register(object())

    def test_requires_resource_type_and_name(self):
        class Bad(PlugExtension):
            extension_name = "bad"

        with self.assertRaises(ValueError):
            ExtensionRegistry.register(Bad())

        class BadName(PlugExtension):
            resource_type = ExtensionResource.account

        with self.assertRaises(ValueError):
            ExtensionRegistry.register(BadName())

    def test_idempotent_reregistration(self):
        ensure_demo_registered()
        ensure_demo_registered()
        ExtensionRegistry.register(DemoAccountExtension())
        obj = ExtensionRegistry.get_extension_obj("account", "demo")
        self.assertIsInstance(obj, DemoAccountExtension)

    def test_conflicting_registration_raises(self):
        ensure_demo_registered()

        class Conflict(PlugExtension):
            resource_type = ExtensionResource.account
            extension_name = "demo"

        with self.assertRaises(ValueError):
            ExtensionRegistry.register(Conflict())

    def test_version_mismatch_is_a_conflict(self):
        ensure_demo_registered()
        other = DemoAccountExtension()
        other.extension_version = "9.9.9"
        with self.assertRaises(ValueError):
            ExtensionRegistry.register(other)

    def test_lookups(self):
        self.assertIsNone(ExtensionRegistry.get_extension_obj("account", "nope"))
        self.assertIsNone(ExtensionRegistry.get_extension_obj("nothing", "nope"))
        self.assertIn("account", ExtensionRegistry.get_extensions())
        self.assertEqual(ExtensionRegistry.get_extensions_for_resource("nothing"), {})
        self.assertIn("core", ExtensionRegistry.get_extensions_for_resource("account"))


class ValidatorFunctionTests(SimpleTestCase):
    def test_non_dict_rejected(self):
        with self.assertRaises(ValueError):
            validate_extensions(["nope"], "account")

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            validate_extensions({"nope": {}}, "account")
        self.assertIn("unknown extension", str(ctx.exception))

    def test_plug_extension_validate_and_normalize(self):
        ensure_demo_registered()
        cleaned = validate_extensions({"demo": {"label": "  hi  "}}, "account")
        self.assertEqual(cleaned, {"demo": {"label": "hi"}})

    def test_plug_extension_schema_violation(self):
        ensure_demo_registered()
        with self.assertRaises(ValueError):
            validate_extensions({"demo": {"label": 42}}, "account")

    def test_plug_extension_custom_rule(self):
        ensure_demo_registered()
        with self.assertRaises(ValueError) as ctx:
            validate_extensions({"demo": {"label": "forbidden"}}, "account")
        self.assertIn("forbidden", str(ctx.exception))
