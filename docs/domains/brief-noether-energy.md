# Domain Brief: noether-energy

Repo: `~/projects/noether-energy`, package `noether_energy`, slug `energy`.
Contract: `authoring-a-domain.md` + `public-api.md`. Same golden rules
(docs/, TDD 100%).

## Scope (v1)

1. **DomainConfig**: account types `source, storage, load, grid` —
   normal balances: source=debit, storage/load/grid=credit (metadata only).
   Default units: `kWh` (precision 3), `Wh` (precision 0).
2. **Chart template `home-microgrid`**: Sources (Solar, Grid:Import),
   Storage (Battery), Loads (House), Grid:Export.
3. **Validators**:
   - `NonNegativeStorage`: accounts of type `storage` may not go below
     zero (uses `balances_after`).
   - `SingleUnitTransactions`: energy transactions must be single-unit
     (no kWh↔Wh mixing within one transaction; conversions are explicit
     ledger operations if ever needed).
4. **MeterAgent role**: registered via RoleController — service identity
   with only `transaction__create` + `transaction__post` + reads,
   for automated meter ingestion.
5. **Ingestion**: a plug endpoint
   `POST /api/v1/plugs/energy/ledgers/{id}/readings` that maps meter
   readings (interval energy flows between named accounts) onto
   posting-service transactions. Idempotent by
   `(ledger, meter_id, interval_start)` — plug-owned dedupe table.
6. **Valuation**: optional `kWh→INR` tariff as a manual UnitPrice series;
   enables billing views via core `?value_in=INR`.

## Out of scope (v1)

Live device integration (MQTT etc.), forecasting, tariff schedules
(time-of-use), water domain (future `noether-water` will clone this shape).
