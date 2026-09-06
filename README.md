# noether

[![codecov](https://codecov.io/gh/vaidyuti/noether/graph/badge.svg)](https://codecov.io/gh/vaidyuti/noether)

Domain-agnostic double-entry **conservation ledger**. Track anything that must
balance — money, energy, water — with one kernel. Domain meaning lives entirely
in plugs (`noether-finance`, `noether-energy`).

## Documentation

All documentation lives in [`docs/`](docs/README.md):

- [`docs/concepts/`](docs/concepts/) — the ledger kernel, valuation, security
- [`docs/adr/`](docs/adr/) — architecture decision records
- [`docs/domains/`](docs/domains/) — writing a domain plug; the frozen public API
- [`docs/api/`](docs/api/) — REST API reference
- [`docs/operations/`](docs/operations/) — testing standard, 12-factor config

## Quick start

```bash
uv sync
make migrate
make run
make test      # full suite, 100% coverage gate
```

## For AI coding agents

**Read [`CLAUDE.md`](CLAUDE.md) before doing anything else.** It contains the
project's golden rules — domain agnosticism, test-driven development with 100%
branch coverage, documentation and ADR requirements, and the definition of done.
`AGENTS.md`, `.cursorrules`, and `.github/copilot-instructions.md` all point at
the same file.

## License

MIT
