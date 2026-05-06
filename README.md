# Agentic Trader

Multi-timeframe pivot scanner that detects trading setups on M5 and notifies via Telegram. See `docs/superpowers/specs/2026-05-05-agentic-trader-design.md` for the full design.

## Status

**Plan 1 (Foundation + Data layer) — implemented.**

Plans 2 (Strategies), 3 (Live MVP + Telegram), 4 (Backtest V2), 5 (Deployment) — pending.

## Quick start (Plan 1 demo)

```bash
pip install -e ".[dev]"
cp .env.example .env  # edit if needed (Plan 1 doesn't require Telegram credentials)
python -m agentic_trader.cli.build_snapshot
```

This fetches the configured watchlist (`config/watchlist.yaml`), computes pivots
for 4H/D/W/M timeframes per symbol via TradingView, persists to SQLite at
`./data/agent.db`, and prints a summary table.

## Tests

```bash
pytest
```

## Project structure

See `docs/superpowers/plans/2026-05-05-plan-1-foundation-and-data-layer.md`
for the file layout and responsibilities.
