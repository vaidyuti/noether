# Domain Brief: noether-finance

Repo: `~/projects/noether-finance`, package `noether_finance`, slug `finance`.
Contract: `authoring-a-domain.md` + `public-api.md`. Same golden rules
(docs/, TDD 100%).

## Scope (v1)

1. **DomainConfig**: account types `asset, liability, equity, income,
   expense, trading` with correct normal balances; default units `INR`
   (precision 2); optionally `USD`.
2. **Chart template `personal-default`**: Assets (Bank, Cash, Brokerage:Cash),
   Liabilities (CreditCard), Income (Salary, CapitalGains, Interest),
   Expenses (Food, Rent, Transport, Utilities, Misc), Equity
   (OpeningBalances), Trading/INR.
3. **Validators**:
   - `EntriesMatchTypeRules`: trading-account entries only in multi-unit
     transactions (warn-level policy: implement as validation).
4. **Investments**: `Holding` helper flows (documented recipes + service
   functions) for buy/sell using the trading-accounts pattern
   (`docs/concepts/02-valuation.md` in core). Cost basis: average-cost
   strategy v1, FIFO later.
5. **ValuationStrategy**: pluggable price provider interface with a
   `manual` provider (prices posted via core API) as default. Real market
   data providers are follow-ups; design the interface, mock in tests.
6. **Extra roles**: none for v1 (built-ins suffice).

## Out of scope (v1)

Budgets, recurring transactions, imports (bank CSV), reports beyond core
balance queries, multi-currency conversion automation.
