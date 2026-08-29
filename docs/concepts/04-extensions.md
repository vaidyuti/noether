# Extensions — extra fields on core models, without forking core

## Why

The kernel is deliberately small and domain-agnostic. But a real deployment
almost always needs to hang one or two extra facts off a core object: a cost
centre on a ledger, a site reference on an account, an upstream document id on
a transaction.

There are two bad ways to do that and one good one:

- fork the core and add columns → every deployment diverges, upgrades hurt;
- push everything into a sidecar table owned by the plug → an extra join and a
  second lifecycle for data that is conceptually *part of the object*;
- **declare a namespaced JSON blob whose shape is validated on write** — that is
  what an extension is.

An extension is a named, schema-validated object stored under a key of the
model's `extensions` JSONField, validated on every write and rendered on every
read.

## Which models carry extensions

| Model | Extensions | Why |
| --- | --- | --- |
| `Ledger` | yes | deployment-level metadata (cost centre, region, owner ref) |
| `Account` | yes | the most common place to attach an external identity |
| `Transaction` | yes | per-event provenance (source document, batch id) |
| `Unit` | no | a unit is an opaque symbol; extending it invites domain meaning into the kernel |
| `Entry` | no | entries are the conservation mechanics; per-leg free-form data would sit inside the balancing invariant |

`ExtensionResource` is the closed enum of extendable resources:
`transaction`, `account`, `ledger`.

## The two sources of extensions

Every extension is one handler object registered in the process-wide
`ExtensionRegistry`, keyed by `(resource_type, extension_name)`.

### 1. Environment-declared — the `core` extension

For each of the three resources, an `EnvExtension` is registered automatically
under the name **`core`**. It has no schema of its own; it reads one from the
environment at call time:

```
NOETHER_EXTENSIONS_<RESOURCE>_<WRITE|READ|RETRIEVE>
```

`<RESOURCE>` is the uppercased resource name (`LEDGER`, `ACCOUNT`,
`TRANSACTION`). The value is a **JSON Schema document, as a JSON string**.

Fallback chain:

- `WRITE` — the schema payloads are validated against on create/update.
- `READ` — falls back to `WRITE` when unset.
- `RETRIEVE` — falls back to `READ` (which may itself fall back to `WRITE`).

If a variable is unset or empty, the schema is `{}` — and an **empty schema
validates anything**. A deployment that declares nothing gets a permissive
`core` extension, not a locked one. If a variable is set but is not parseable
JSON, the read raises `ValueError` naming the offending key — a deployment
misconfiguration fails loudly rather than silently degrading to "no schema".

### 2. Plug-registered — code-declared extensions

A plug subclasses `PlugExtension`, sets its schemas in code, and registers the
instance from its `AppConfig.ready()`. It may also override the validate and
render hooks, which the environment variant cannot.

## Handler surface

```python
class ExtensionBase:
    resource_type: ExtensionResource | None
    extension_name: str
    extension_version: str
    extension_owner: ExtensionOwner  # core | plug

    write_schema: dict
    read_schema: dict  # falls back to write_schema
    retrieve_schema: dict  # falls back to read_schema

    def validate(self, data, resource=None): ...  # write: raise ValueError to reject
    def serialize_extensions(self, data, resource=None): ...  # write: normalize before persist
    def deserialize_extensions_list(self, data, resource): ...  # read: list rendering
    def deserialize_extensions_retrieve(self, data, resource): ...  # read: retrieve rendering
```

`validate()` raising `ValueError` is the rejection channel; the pydantic spec
layer turns it into a 400. The class-level `read_schema` / `retrieve_schema`
fallbacks mirror the environment fallback chain exactly, so the two sources
behave the same way.

## Strictness — unknown extension keys are REJECTED

On write, every key of the incoming `extensions` mapping is looked up in the
registry. **A key with no registered handler is a 400**, not a silently dropped
field and not a silently stored one:

```python
handler = ExtensionRegistry.get_extension_obj(resource_type, key)
if handler is None:
    raise ValueError(f"unknown extension {key!r} for resource {resource_type!r}")
```

`extensions` must also be a JSON object; a list or a scalar is a 400.

Strict was chosen because the alternative loses data quietly. A payload naming
an extension nobody declared means one of two things: the client is buggy, or
the deployment is stale (the plug that owned that key is not loaded). Both are
conditions the caller must learn about *at write time*. Accepting the write and
returning a response that does not contain what was sent is the worst possible
outcome — the client believes it stored something it did not.

## Read rendering — the full declared surface, always

Reads do not echo storage. For each read, the renderer walks **every handler
registered for the resource** and renders `stored.get(key, {})` through it. So:

- a declared extension that has never been written appears as `{}` rather than
  being absent — the response shape is stable and self-describing;
- a handler may compute or decorate on read (list and retrieve have separate
  hooks, so a retrieve can be richer than a list entry).

## Worked example — environment-declared

Declare a cost centre on ledgers:

```bash
export NOETHER_EXTENSIONS_LEDGER_WRITE='{
  "type": "object",
  "properties": {"cost_centre": {"type": "string"}},
  "additionalProperties": false
}'
```

Create:

```bash
curl -X POST /api/v1/ledgers/ -H 'Content-Type: application/json' -d '{
  "domain": "testdomain",
  "name": "Ext Ledger",
  "extensions": {"core": {"cost_centre": "CC-1"}}
}'
# 201
# { "id": "...", "name": "Ext Ledger",
#   "extensions": {"core": {"cost_centre": "CC-1"}} }
```

Violate the schema:

```bash
curl -X POST /api/v1/ledgers/ -d '{"domain":"testdomain","name":"Bad",
  "extensions": {"core": {"cost_centre": 7}}}'
# 400 — extension 'core' payload is invalid: 7 is not of type 'string'
```

Name an extension nobody declared:

```bash
curl -X POST /api/v1/ledgers/ -d '{"domain":"testdomain","name":"Bad",
  "extensions": {"nope": {}}}'
# 400 — unknown extension 'nope' for resource 'ledger'
```

## Worked example — plug-registered

```python
# myplug/extensions.py
from noether.extensions import ExtensionRegistry, ExtensionResource, PlugExtension


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
        super().validate(data, resource)  # JSON Schema first
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
```

```python
# myplug/apps.py
from django.apps import AppConfig


class MyPlugConfig(AppConfig):
    name = "myplug"

    def ready(self):
        from noether.extensions import ExtensionRegistry
        from myplug.extensions import DemoAccountExtension

        ExtensionRegistry.register(DemoAccountExtension())
```

Registration is **idempotent**: `ready()` can run more than once, and
re-registering an equivalent handler (same class, same `extension_version`) is
a no-op. Registering a *different* handler under a name already taken for that
resource raises — a name collision between two plugs is a deployment error, not
a last-one-wins race.

Using it — note the trimmed label and the retrieve-flavoured rendering:

```bash
curl -X POST /api/v1/ledgers/my-ledger/accounts/ -d '{
  "name": "Ext Account", "account_type": "generic", "unit": "<unit-uuid>",
  "extensions": {"demo": {"label": "  boxed  "}, "core": {"cost_centre": "CC-9"}}
}'
# 201
# "extensions": {
#   "demo": {"label": "boxed", "rendered": "retrieve"},
#   "core": {"cost_centre": "CC-9"}
# }

curl /api/v1/ledgers/my-ledger/accounts/            # list  → "rendered": "list"
curl /api/v1/ledgers/my-ledger/accounts/<id>/       # detail → "rendered": "retrieve"
```

## Interaction with immutability (ADR-0001)

Extensions are **part of the transaction**, not metadata beside it. They obey
the same rule as everything else on a transaction:

- **draft** transaction → `PUT`/`PATCH` of `extensions` succeeds, `200`;
- **posted** transaction → any write, including one that touches only
  `extensions`, is refused with **409**.

There is no escape hatch. If a posted transaction's extension data is wrong,
correct it the way every other posted-transaction error is corrected: a
reversal transaction plus a replacement. This is deliberate — an "extensions
are editable after posting" carve-out would make the extension blob a
convenient place to hide mutable state on an immutable record, and the audit
guarantee of ADR-0001 would be worth exactly as much as the honesty of whoever
chose which field to use.

Ledgers and accounts are not immutable, so their extensions are freely
updatable.

## Limits worth knowing

- Extension data lives in a JSONField. It is **not a column**: it is not
  indexed, not efficiently filterable, and not usable as a foreign key. If you
  need to query on it at scale, it wants to be a real field in a plug-owned
  model.
- Because schemas are declared per deployment, **the API payload shape is
  deployment-dependent**. A client written against one deployment's `core`
  schema may get a 400 against another's. Clients that must be portable should
  treat unknown extension content as opaque and write only what they declared.

See ADR-0012 for the decision record.
