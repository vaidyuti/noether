# Tags

Tags are **metadata labels applied to ledger rows**. They are not ledger
entries: applying or removing a tag never changes a balance, never touches
conservation, and — deliberately — is allowed on **posted** transactions
(ADR-0001 immutability governs the accounting record, not its labels).

## Scope

A `TagConfig` belongs to exactly one **ledger**. There is no global tag
vocabulary, no organization-level tag tree, and no cross-ledger reuse: a tag
config from ledger A can never be applied to a row in ledger B. Attempting it
is rejected as `unknown tag <id> in this ledger`.

Each config declares the `resource` it applies to (`transaction` today). A tag
whose `resource` does not match the tagged model's resource type is rejected.

## Storage

Tags live **denormalized on the tagged row**: an `ArrayField` of `TagConfig`
integer primary keys, contributed by the abstract `TaggableMixin`. Any model
opts in by inheriting it:

```python
from noether.tagging.models import TaggableMixin


class Transaction(TaggableMixin, NoetherBaseModel): ...
```

Reading a row's tags therefore costs no join, and filtering is an array
overlap/containment lookup. The tradeoff is deliberate and recorded in
ADR-0013: there is **no per-assignment audit trail** (no "who tagged this,
when" row).

## Hierarchy

Configs form a tree via `parent`. On create, the row materializes its ancestry:

| Field | Meaning |
| --- | --- |
| `level_cache` | depth; a root is `0` |
| `parent_cache` | ancestor ids, root-first |
| `root_tag_config` | the top-most ancestor |
| `has_children` | set on the parent when its first child appears |
| `cached_parent_json` | denormalized ancestry blob for read APIs, with `cache_expiry` (15 days) |

`get_parent_json()` returns the cached blob while it is fresh and recomputes
(and re-persists) it once `cache_expiry` has passed.

## Configurable exclusivity

`exclusive_children` is a boolean set on a **parent**. When true, at most one
tag from that parent's **subtree** may be applied to a given row.

Worked example:

```
Colour            exclusive_children = True
├── Warm
│   └── Red
└── Cool
    └── Blue

Size              exclusive_children = False
├── Big
└── Small
```

- apply `Red` → ok.
- apply `Blue` → **400**: `tag 'Colour' allows only one tag from its subtree;
  'Red' is already applied`. `Blue` sits under `Cool`, a different branch, but
  the governing exclusive ancestor is the same `Colour`.
- apply `Big`, then `Small` → both accepted; `Size` is not exclusive, so
  siblings coexist freely.

Exclusivity is evaluated against every ancestor of the tag being applied, so
setting it on a deep node scopes the constraint to just that node's subtree.

## Rejection rules

`set_tag` rejects when the tag is unknown in this ledger, its `resource`
mismatches, it is already applied, an exclusive ancestor already governs an
applied tag, or the user lacks `tag__apply`. `unset_tag` additionally rejects
removing a tag that is not applied.

## Permissions

| Slug | Owner | Bookkeeper | Auditor | Viewer |
| --- | --- | --- | --- | --- |
| `tag__read` | yes | yes | yes | no |
| `tag__write` | yes | yes | no | no |
| `tag__apply` | yes | yes | no | no |

## API

See `docs/api/rest-api.md` for the tag-config CRUD collection, the
`set-tag` / `unset-tag` transaction actions, and the `tags` / `tags_all` list
filters.
