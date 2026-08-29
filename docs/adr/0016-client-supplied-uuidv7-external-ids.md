# ADR-0016: Client-supplied UUIDv7 external IDs

- **Status:** Accepted
- **Date:** 2026-08-29
- **Supersedes (in part):** [ADR-0015](0015-bulk-upsert.md)

## Context

Every `NoetherBaseModel` carries an `external_id`: a unique, indexed `UUIDField`
that is the only identifier the API exposes. It was minted server-side with
`uuid.uuid4`, and `NoetherResource.de_serialize` explicitly refused to write it,
so a client could not choose one.

Two problems follow from that, and both get worse as a ledger accumulates
history.

**Index locality.** UUIDv4 is pure randomness. Every insert lands at an
arbitrary point in the `external_id` B-tree, so the working set of hot index
pages is the whole index rather than its tail. On an append-heavy table —
which is exactly what a conservation ledger is, since posted transactions are
immutable (ADR-0001) and only ever accumulate — this means page splits and
cache misses that grow with table size.

**Idempotent retries.** A client that posts a transaction and then loses the
connection cannot tell "the write committed and the ack was lost" from "the
write never happened". Retrying risks a duplicate transaction; not retrying
risks a lost one. With a server-minted id there is no stable handle to ask
about, so the client has no safe move. This is not hypothetical for a ledger:
a duplicated transaction is a real balance error.

## Decision

**1. `external_id` defaults to UUIDv7.** `noether.ledger.models_base.generate_external_id`
wraps `uuid_utils.compat.uuid7` and is the field default. UUIDv7 (RFC 9562) is
a 48-bit millisecond timestamp followed by randomness, so ids are time-ordered
and inserts land at the tail of the index. The column type does not change —
v7 is still a 128-bit UUID.

We took the dependency on `uuid-utils` because CPython only gained
`uuid.uuid7()` in 3.14 and this project targets 3.13. `uuid_utils.compat.uuid7()`
returns a genuine `uuid.UUID`, so Django needs no field adapter.

**2. Clients may supply `external_id` on create.** Any resource using
`NoetherCreateMixin` accepts an `id` in the create body. When present it becomes
the row's `external_id`; when absent one is minted. This makes the primary
identifier double as the idempotency key: a retry carries the same id, so the
server can recognise it.

**3. A replayed id is resolved by comparing the request to the stored row.**

- Body renders to the same resource as the stored row → **200** with the stored
  row. The retry is a no-op.
- Body renders to something different → **409** `id_conflict`.
- Id already belongs to a row this user cannot see → **409** `id_unavailable`,
  never 404. The id space is global; a caller that picked a colliding id needs
  to know it is taken, and this leaks no more than the fact of the collision.

We chose "200 only if the body matches" over "200 always" deliberately. Always
returning the stored row would silently ignore a genuinely different request
that happened to reuse an id — a client bug rendered invisible, and in a ledger
an invisible write failure is worse than a loud one.

Comparison is on the *rendered* resource, not the raw body, so field ordering,
absent-vs-default fields, and equal-but-differently-written decimals
(`100.00` vs `100.0000000000`) do not produce spurious conflicts.

**4. Two ADR-0015 upsert behaviours are superseded.** In a bulk upsert:

- an `id` that matches nothing now **creates the row with that id**, rather
  than creating it with a freshly minted one. Otherwise a re-run of the same
  import would not converge — the second run could not find what the first
  created.
- a malformed `id` is now a **400**, rather than being treated as a create.
  Once an id carries idempotency meaning, silently discarding an unparseable
  one converts a botched retry into a duplicate row, which is the exact failure
  this ADR exists to prevent.

## Consequences

- Existing UUIDv4 rows keep their ids. v4 and v7 coexist in the column
  indefinitely; nothing reads a version bit, and rewriting historical ids would
  destroy identity. Locality improves for new rows only.
- Ids are no longer opaque: a UUIDv7 leaks its creation timestamp to whoever
  holds it. For ledger objects this is not sensitive — creation time is already
  a readable field. Anything genuinely secret (tokens, invite codes) must not
  use `external_id`.
- Clients can now choose ids, so a caller may pick one that collides. The
  409 responses make this explicit rather than corrupting data.
- Because the create path may now return 200, callers that assert `status == 201`
  on create need updating; `2xx` is the correct check.
- Ids remain unguessable in practice: 74 bits of randomness per millisecond is
  ample against enumeration, and RBAC scoping remains the actual access control.

## Alternatives considered

**ULID.** Same time-ordering property, but it is not an RFC, has no native
database type, and would force `external_id` to `char(26)` or `binary(16)`
with bespoke encoding. The Base32 readability it buys is worth nothing here,
since these ids are not typed by humans.

**A separate `idempotency_key` column.** Keeps ids server-controlled, but it is
a second unique index on every table and reimplements client-supplied ids in a
weaker form — the client still has to generate and store a key, but now the row's
own identifier is not it.

**Postgres-side `uuidv7()` default.** Available in Postgres 18, but it would put
the default out of reach of the client-supplied path and split id generation
across two layers. Generating in Python keeps one code path.
