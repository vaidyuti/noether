# Valuation, Investments, and Cross-Unit Flows

Decided in ADR-0002: **valuation is an overlay, never a ledger entry.**

## The two dimensions of an investment

An investment account (mutual fund, stock, battery-stored energy priced for
billing…) is an ordinary account whose unit is the *holding* unit
(`AAPL`, `MF-XYZ`), not the money unit. Quantity is tracked by the ledger;
**value is computed**, not stored.

```
Accounts:
  Assets:Brokerage:Cash        unit=INR
  Assets:Brokerage:AAPL        unit=AAPL
  Trading:INR                  unit=INR     (see below)
  Trading:AAPL                 unit=AAPL
```

## Cross-unit transactions: the trading-accounts pattern

Kernel law says a transaction balances **per unit**. A purchase involves two
units, so each unit's legs balance through explicit *trading accounts*
(the GnuCash/Sheets-of-old pattern — the domain's chart template provides
them; the kernel doesn't know they're special):

"Buy 5 AAPL for ₹75,000":

```
Transaction: "Buy AAPL"
  CREDIT  Assets:Brokerage:Cash    75000  INR
  DEBIT   Trading:INR              75000  INR
  DEBIT   Assets:Brokerage:AAPL        5  AAPL
  CREDIT  Trading:AAPL                 5  AAPL
```

Both INR legs balance; both AAPL legs balance; conservation holds per unit.
Trading account balances are the cumulative record of cross-unit exchange —
exactly the boundary-account insight applied to unit boundaries.

Domains that never cross units (a pure kWh ledger) simply never create
trading accounts.

## UnitPrice: the valuation overlay

```
UnitPrice:
  ledger (FK), unit (FK), quote_unit (FK),
  price (Decimal 30,10), as_of (datetime), source (string), metadata (jsonb)
```

- Append-only time series. Written by domain valuation strategies
  (Celery tasks fetching market data) or manually via API.
- **Market value** of an account = `balance × latest price(unit → quote_unit
  as_of ≤ t)`. Computed at read time (API exposes
  `?value_in=<unit>&as_of=<t>`), never persisted into entries.
- Unrealized gain = market value − cost basis. Cost basis derivation
  (FIFO/average) is a **domain** computation over the account's entries;
  the kernel exposes the entries, the domain (e.g. noether-finance)
  implements basis strategies.

## Realized gains

Realized at sale time by an ordinary transaction — the gain leg posts to a
real account (`Income:CapitalGains`), keeping the ledger factual:

"Sell 5 AAPL for ₹90,000 (cost ₹75,000)":

```
  DEBIT   Assets:Brokerage:Cash    90000  INR
  CREDIT  Trading:INR              90000  INR
  CREDIT  Assets:Brokerage:AAPL        5  AAPL
  DEBIT   Trading:AAPL                 5  AAPL
```

(The ₹15,000 gain is visible as the change in Trading:INR net of AAPL flows;
noether-finance MAY additionally model explicit gain-splitting entries —
that is domain policy, not kernel law.)

## Non-finance uses of the same machinery

- Energy: `UnitPrice(kWh → INR)` time series enables billing views without
  polluting the energy ledger with money.
- Water: litres → INR for utility-cost dashboards.

The kernel ships `UnitPrice` because it is domain-agnostic time-series data
keyed on kernel objects; every *strategy* that writes or interprets it
lives in a plug.
