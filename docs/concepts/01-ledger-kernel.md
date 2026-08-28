# The Ledger Kernel

The kernel is the core Django app (`noether/ledger/`). It defines six
primitives and enforces their invariants. Everything else in the system is
built on these.

## Primitives

### Domain

A registered quantity-domain, contributed by a plug (see
`docs/domains/authoring-a-domain.md`). Rows in the `Domain` table mirror the
in-code `DomainConfig` registry (synced by a management command, like Care's
`sync_permissions_roles`). A `Domain` row carries only: `slug`, `name`,
`version`, `enabled`.

### Ledger

The bookkeeping and authorization boundary.

- Belongs to exactly one `Domain`.
- Owns its account tree, transactions, and memberships.
- Fields: `external_id (uuid)`, `domain (FK)`, `name`, `description`,
  `settings (jsonb — domain-namespaced)`, audit fields.
- Deleting a ledger is soft-delete (`deleted` flag), consistent with all
  kernel models.

### Unit

The unit-of-measure of a conserved quantity, scoped to a ledger.

- Fields: `ledger (FK)`, `symbol` (e.g. `INR`, `kWh`, `AAPL`),
  `name`, `precision` (int, decimal places for validation), `metadata (jsonb)`.
- Core treats units as **opaque**: no arithmetic across units, ever.
  A transaction balances *per unit*.
- Unique: `(ledger, symbol)`.
- Units representing holdings (e.g. a stock ticker) are ordinary units.

### Account

A node that holds a balance of exactly one unit.

- Fields: `ledger (FK)`, `parent (FK self, nullable)`, `name`,
  `account_type (string — validated against the domain's registered types)`,
  `unit (FK)`, `is_placeholder` (bool: structural node, cannot hold entries),
  `archived` (bool), `metadata (jsonb)`.
- Tree constraint: parent must belong to the same ledger. Path/depth kept
  simple (adjacency list + recursive CTE); no MPTT dependency.
- Accounts are **archived**, never deleted, once they have entries.
- `account_type` semantics (normal balance side, sign policy) are domain
  concerns; the kernel only checks the type exists in the ledger's domain.

### Transaction

The atomic conservation event.

- Fields: `ledger (FK)`, `status` (`draft` | `posted` | `reversed`),
  `description`, `occurred_at` (timezone-aware; the economic/physical time),
  `posted_at` (set at post time), `reverses (FK self, nullable)`,
  `reversed_by (FK self, nullable)`, `metadata (jsonb)`, audit fields.
- Must contain ≥ 2 entries to be postable (see invariants).

### Entry

One leg of a transaction.

- Fields: `transaction (FK)`, `account (FK)`, `direction`
  (`debit` | `credit`), `amount` (Decimal(30,10), strictly > 0),
  `metadata (jsonb)`.
- Entry's account must belong to the transaction's ledger, must not be a
  placeholder, and must not be archived (at post time).
- The entry's unit is **derived from its account** — an entry has no unit
  field of its own. This makes per-unit balancing unambiguous.

## Derived state

### AccountBalance

Materialized current balance per account, updated inside the posting
transaction under `select_for_update`. Read-optimized; never the source of
truth. `balance` is signed: debits minus credits (presentation sign is a
domain concern via the account type's normal side).

### BalanceSnapshot

Periodic per-account `(as_of, balance)` rows written by Celery. Point-in-time
balance = latest snapshot ≤ t + replay of entries in (snapshot, t]. Also the
basis of the integrity verifier.

## Invariants (kernel law — enforced in code, tested property-based)

1. **Conservation**: for a postable transaction, per unit,
   Σ debit amounts = Σ credit amounts, exactly (Decimal, no tolerance).
2. **Positivity**: every entry amount > 0. Direction is carried by
   `direction`, never by sign.
3. **Precision**: every amount conforms to its account's unit precision.
4. **Immutability**: a `posted` transaction and its entries are immutable.
   No update, no delete. Corrections are reversals (ADR-0001).
5. **Reversal**: reversing creates a new posted transaction with mirrored
   entries (debit↔credit), sets `reverses` on the new and `reversed_by` on
   the old, and flips the old status to `reversed`. A transaction can be
   reversed at most once. Reversal transactions can themselves be reversed
   (re-instating the effect) — the chain is explicit.
6. **Same-ledger closure**: all entries in a transaction reference accounts
   of the transaction's ledger.
7. **Balance identity**: for every account at all times,
   `AccountBalance.balance ≡ Σ(debits) − Σ(credits)` over posted entries.
   The integrity verifier re-derives and alarms on drift.
8. **Minimum arity**: a postable transaction has ≥ 2 entries.
   (A single-unit transaction therefore always has both a debit and a credit.)

## Lifecycle

```
        create (draft)          post                   reverse
  ──────────────────────▶ DRAFT ─────▶ POSTED ────────────────▶ REVERSED
                            │  editable   │ immutable              │ immutable
                            │  deletable  │ affects balances       │ balances restored
                            └─ validators run at post time ────────┘
```

- **Draft**: fully mutable, invisible to balances. May be validated
  eagerly (best-effort) but authoritative validation happens at post.
- **Post**: single atomic DB transaction: lock affected `AccountBalance`
  rows (ordered by account id — deadlock avoidance), run kernel invariants,
  run domain validators, write `posted_at`, apply balance deltas.
- **Reverse**: creates and posts the mirror transaction atomically.
- Direct-post convenience: `POST /transactions/` with `post: true` creates
  and posts in one request (still two conceptual steps internally).

## Explicitly out of kernel scope

- Sign constraints ("balance may not go negative") — domain validator hook.
- Unit conversion / multi-currency arithmetic — domain concern (an exchange
  is a transaction with entries in two units, each side balancing… see
  `02-valuation.md` for the pattern).
- Valuation, pricing, market value — overlay, see `02-valuation.md`.
- Recurring transactions, budgets, reports — future core-adjacent modules
  or domain features.
