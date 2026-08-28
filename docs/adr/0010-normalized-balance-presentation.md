# ADR-0010: Normalized Balance Presentation

- Status: Accepted
- Date: 2026-08-28
- Deciders: Rithvik Nishad

## Context

The kernel stores balances raw and signed: `balance ≡ Σ(debits) − Σ(credits)`
(ADR-0007, concepts/01). Presentation sign was declared "a domain concern via
the account type's normal side" but nothing in core ever applied it. In
practice every consumer saw the raw value:

- the `balance` API endpoint returned raw,
- validators received raw `balances_after`,
- plugs had to reason about "credit-normal ⇒ stored energy is negative"
  (noether-energy's `NonNegativeStorage` inverted its comparison).

This confused even the plug authors and produced counter-intuitive reads
("a charged battery has balance −5"). Accounting software universally solves
this with the **normal-balance convention**: display each account's balance
relative to its normal side so a correctly-typed account in its natural state
reads positive (an asset bank account after a deposit: +; an income account
after earning: +).

## Decision

1. The kernel's stored/derived raw balance remains `Σdebits − Σcredits`.
   Conservation math, `AccountBalance` rows, and `BalanceSnapshot` rows are
   unchanged.
2. Core now *applies* the normal side it already receives via
   `AccountTypeDef.normal_balance`:
   `normalized(account) = raw × (+1 if normal_balance == "debit" else −1)`.
3. **All presentation and hook surfaces speak normalized:**
   - The account `balance` endpoint returns `balance` (normalized) and
     `raw_balance`.
   - `get_balance()` returns normalized; `get_raw_balance()` returns raw.
     `get_market_value()` values the normalized quantity.
   - `TransactionValidator.validate` receives `balances_after` **normalized
     per account**; validators no longer need to know sides.
4. An account whose `account_type` has no registered `AccountTypeDef` in its
   ledger's domain is treated as debit-normal (normalized ≡ raw).

## Consequences

- Positive means "this account holds what it normally holds" — everywhere,
  for every domain. Battery stores 5 kWh ⇒ `+5`. Salary income earned ⇒ `+`.
- Sign-policy validators become trivial (`normalized ≥ 0`).
- Raw values stay available (`raw_balance`, `get_raw_balance`) for
  conservation math and audits.
- Breaking for existing validators/consumers that compensated for raw signs
  (noether-energy updated in lockstep; pre-release, no data migration needed).

## Alternatives considered

- **Flip the kernel to credits − debits**: merely mirrors the problem
  (assets/expenses/storage would read negative in finance). Rejected.
- **Leave presentation to each plug**: the status quo; every plug re-derives
  the same convention and some get it wrong. Rejected.
- **Store normalized in AccountBalance**: makes the stored fold depend on
  mutable domain config and complicates conservation checks. Rejected.
