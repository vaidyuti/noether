# Noether Documentation

> **Noether** — a domain-agnostic conservation ledger. Track the flow of any
> conserved quantity (money, energy, water, …) with double-entry semantics.
> Named for Emmy Noether: conservation laws arise from symmetries; here,
> conservation is enforced by construction.

## Structure

| Section | Purpose |
| --- | --- |
| [`concepts/`](concepts/) | The domain model: ledger kernel primitives, invariants, lifecycles. Read these first. |
| [`adr/`](adr/) | Architecture Decision Records. Numbered, immutable once accepted (superseded, never edited). |
| [`domains/`](domains/) | The domain-plugin contract: how `noether-finance`, `noether-energy`, etc. extend the core. |
| [`api/`](api/) | REST API conventions and surface. |
| [`operations/`](operations/) | 12-factor config, deployment, Celery topology, testing standard. |

## Reading order for new contributors (human or agent)

1. `concepts/00-overview.md` — the mental model
2. `concepts/01-ledger-kernel.md` — primitives and invariants
3. `adr/` — all accepted ADRs (they are the binding contracts)
4. `domains/authoring-a-domain.md` — if building a plug
5. `operations/testing-standard.md` — before writing any code

## Golden rules (non-negotiable)

1. **All documentation lives in `docs/`** — hierarchical markdown. Code
   comments explain *how*; docs explain *what* and *why*.
2. **TDD with 100% coverage from day 0.** Statement + branch coverage at
   100% (`fail_under = 100`, `branch = True`), MC/DC-by-policy for compound
   conditions. See `operations/testing-standard.md` and ADR-0003.
3. **The core is domain-agnostic.** No domain vocabulary (money, energy,
   price, invoice, kWh…) may appear in core models, APIs, or migrations.
   Domain meaning lives exclusively in plugs.
