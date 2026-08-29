# ADR-0012: JSON-Schema-validated model extensions on Ledger/Account/Transaction

- Status: Accepted
- Date: 2026-08-29
- Deciders: core maintainers

## Context

The kernel is domain-agnostic by construction: money, energy and water all map
onto the same six primitives, and nothing domain-specific may enter `noether/`.
That constraint holds well for *mechanics* but leaves a real gap for *data*.

Every non-trivial deployment needs to attach a small amount of extra
information to core objects — a cost centre on a ledger, an upstream system's
identifier on an account, a source document reference on a transaction. Two
distinct parties need this, for different reasons and on different timescales:

- **a deployment**, which wants one or two extra fields configured at deploy
  time and has no appetite for writing Python;
- **a plug**, which owns a coherent domain concept and wants schema *plus*
  behaviour (normalization, cross-field rules, computed read values).

Without a sanctioned mechanism, both end up either forking the core to add
columns (divergence, painful upgrades) or maintaining sidecar tables joined on
every read (an extra lifecycle for data that conceptually belongs to the
object).

## Decision

Add an `extensions` JSONField to `Ledger`, `Account` and `Transaction`
(migration `0004`), holding a mapping of *extension name* → *extension object*.

1. **Every extension is a registered handler.** `ExtensionRegistry` maps
   `(resource_type, extension_name)` → handler instance. `ExtensionResource` is
   a closed enum: `ledger`, `account`, `transaction`.
2. **Two declaration sources.**
   - *Environment-declared*: an `EnvExtension` is auto-registered for each
     resource under the name `core`. Its schemas come from
     `NOETHER_EXTENSIONS_<RESOURCE>_<WRITE|READ|RETRIEVE>`, each holding a JSON
     Schema document as a JSON string, with `READ` falling back to `WRITE` and
     `RETRIEVE` falling back to `READ`. An unset variable yields `{}`, which
     validates anything; an unparseable one raises, naming the key.
   - *Plug-registered*: a plug subclasses `PlugExtension`, declares schemas in
     code, may override `validate` / `serialize_extensions` /
     `deserialize_extensions_{list,retrieve}`, and registers the instance from
     its `AppConfig.ready()`.
3. **Unknown extension keys on write are rejected with 400.** A key with no
   registered handler is an error. `extensions` must be a JSON object.
4. **Registration is idempotent.** Re-registering an equivalent handler (same
   class, same `extension_version`) for a name already held is a no-op;
   registering a *different* handler under a taken name raises.
5. **Reads render the full declared surface.** Every handler registered for the
   resource is rendered, defaulting to `{}` when nothing is stored, so the
   response shape does not depend on write history. List and retrieve have
   separate render hooks.
6. **Extensions are not added to `Unit` or `Entry`.**
7. **Extensions inherit ADR-0001 immutability.** Editing extensions on a draft
   transaction is a `200`; on a posted transaction it is a `409`.

## Consequences

Positive:

- A deployment gains custom fields with an environment variable and no code,
  no fork, and no migration.
- A plug gains fields *with behaviour* — normalization on write, computed values
  on read — without touching core models.
- Validation is centralized in the spec layer, so every write path (create,
  update, bulk) is covered by the same rule, and errors arrive as normal 400s in
  the standard error shape.
- Read responses are self-describing: a client can see the full set of declared
  extensions from any response, not just the ones previously written.
- Separate list and retrieve render hooks let expensive rendering be confined to
  detail responses.

Negative:

- **Extension data is not a column.** It is not indexed, not efficiently
  filterable, and cannot participate in foreign keys or constraints. Anything
  that must be queried at scale still wants a real field on a plug-owned model.
  This ADR does not make JSON a substitute for schema design.
- **Payload shape becomes deployment-dependent.** The same request body may be
  a 201 on one deployment and a 400 on another, because the `core` schema is
  configuration. Portable clients must treat extension content as opaque and
  write only what they declared.
- Schema errors are only discoverable at write time; there is no compile-time or
  startup-time check that a client and a deployment agree.
- Configuration carries structure. A JSON Schema in an environment variable is
  awkward to author and easy to break; a malformed one fails on first use rather
  than at boot.
- A misregistering plug can collide on an extension name and prevent the process
  from starting cleanly. This is intentional (see below) but it is still an
  operational failure mode.

Neutral:

- Handlers carry `extension_version`, which currently participates only in the
  idempotency equivalence check. It is not yet used for payload versioning.
- `extension_owner` (`core` | `plug`) records provenance and is available for
  introspection; nothing in the write path branches on it.

## Alternatives considered

**Silently tolerate unknown extension keys** (drop them, or store them
unvalidated). Rejected. Both variants lie to the caller: the request succeeds
and the response does not contain what was sent, so the client believes it
persisted data it did not. An unknown key has exactly two causes — a buggy
client, or a deployment missing the plug that owns the key — and both are
conditions the caller must learn about at write time, loudly. Tolerance also
turns `extensions` into an unvalidated dumping ground, at which point the
schema declarations are decorative. Strictness costs a clear 400 during
integration; tolerance costs silent data loss in production.

**One pydantic model per extension, instead of JSON Schema.** Rejected for the
environment-declared half: pydantic models are Python, and a deployment cannot
add one without shipping code — which is precisely the fork we are avoiding.
JSON Schema is data, so it travels in an environment variable, is portable
across clients and languages, and can be published to consumers as-is. Using
pydantic for plugs and JSON Schema for the environment would mean two
validation engines, two error shapes, and two mental models; one mechanism for
both sources is worth more than the marginal ergonomics of typed models. Plugs
that want stronger typing can still validate with pydantic inside their own
`validate()` hook.

**Last-registration-wins in the registry.** Rejected. Django may call
`AppConfig.ready()` more than once in a process, so registration must be
idempotent regardless — but idempotency for *equivalent* handlers is not the
same as silently replacing a *different* one. Two plugs claiming the same
extension name for the same resource is a deployment composition error; letting
import order decide which one validates writes would produce behaviour that
differs between environments for no visible reason. Equivalence is judged on
handler class and `extension_version`, so a genuine repeat call is free and a
genuine conflict raises.

**Extensions on `Unit` and `Entry` as well.** Rejected. A unit is deliberately
an opaque symbol; giving it a free-form payload is the shortest path to domain
meaning leaking into the kernel. An entry is the conservation mechanic itself —
per-leg free-form data would sit inside the balancing invariant, and any
behaviour attached to it would be behaviour attached to the invariant. Both
needs are served by extending the owning `Account` or `Transaction` instead.

**Exempt extensions from posted-transaction immutability**, so that operational
metadata could be corrected in place. Rejected. It would create a mutable
region on an otherwise immutable record, and nothing would stop it becoming the
preferred home for state that should have been a real field. ADR-0001's audit
guarantee is only worth something if it has no exceptions; corrections go
through reversal, extensions included.

**Sidecar tables owned by plugs, with no core mechanism.** Rejected as the sole
answer: it is the right tool for large, queryable, relational domain data, and
plugs remain free to use it. But it is disproportionate for two scalar fields,
it adds a join to every read, and it gives deployments without a plug no option
at all.
