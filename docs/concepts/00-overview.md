# Overview: What Noether Is

Noether is a **conservation ledger**: a system for recording the movement of
conserved quantities between accounts, such that the total is always
accounted for. Double-entry bookkeeping is the 700-year-old special case;
Noether generalizes it to any quantity.

## The one-sentence model

> A **Transaction** moves amounts between **Accounts** in a **Ledger**, via
> **Entries** that must balance (Σ debits = Σ credits per unit), and the
> **Domain** (a plugin) gives those movements meaning.

## Worked examples

### Finance (noether-finance)

"Paid ₹500 for groceries from bank account":

```
Transaction: "Groceries"
  Entry: CREDIT  Assets:Bank        500 INR
  Entry: DEBIT   Expenses:Food      500 INR
```

### Energy (noether-energy)

"Solar panels generated 10 kWh; 5 to battery, 5 consumed":

```
Transaction: "Solar generation 2026-08-27 12:00"
  Entry: DEBIT   Sources:Solar      10 kWh   ← the world outside the system
  Entry: CREDIT  Storage:Battery     5 kWh
  Entry: CREDIT  Loads:House         5 kWh
```

## The boundary insight

Nothing is created or destroyed **inside** a ledger. Apparent creation
(income, solar generation, water inflow) is modeled by making the outside
world an explicit account (`Sources:*`, `Income:*`), exactly as classical
accounting treats Equity and Income. The core therefore never needs
concepts like "generation" or "income" — those are domain vocabulary
assigned to ordinary accounts by plugs.

## What the core knows and doesn't know

| Core knows | Core does NOT know |
| --- | --- |
| Ledgers, accounts, account trees | What an "expense" or "battery" is |
| Units as opaque symbols + precision | Currency codes, kWh, litres semantics |
| Transactions, entries, balancing | Whether negative balances make sense |
| Draft → posted → reversed lifecycle | Valuation, prices, market data |
| Balances, snapshots, integrity | Reporting categories, budgets |
| RBAC: users, roles, ledger membership | Domain-specific roles beyond built-ins |

## System shape

```
┌────────────────────────────────────────────────────┐
│  plugs: noether-finance   noether-energy   (…)     │
│    DomainConfig: account types, units, validators, │
│    valuation, chart templates, roles, permissions  │
├────────────────────────────────────────────────────┤
│  noether core                                      │
│    ledger kernel │ domain registry │ security(RBAC)│
│    users │ REST API (DRF + pydantic specs)         │
├────────────────────────────────────────────────────┤
│  PostgreSQL 16     Redis      Celery (+beat)       │
└────────────────────────────────────────────────────┘
```
