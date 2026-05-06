# Agentic Trader

Multi-timeframe pivot scanner that detects trading setups on M5 and notifies via Telegram. See `docs/superpowers/specs/2026-05-05-agentic-trader-design.md` for the full design.

## Status

**Plan 1 (Foundation + Data layer) — implemented.**
**Plan 2 (Strategies S1-S6) — implemented.**
**Plan 3 (Live MVP + Telegram) — implemented.**

Plans 4 (Backtest V2), 5 (Deployment) — pending.

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

## Strategies (Plan 2)

Six pluggable detection units in `src/agentic_trader/strategies/`:

| ID | File | Trigger |
|---|---|---|
| S1 | `s1_bounce.py` | Wick + close back on PDL/S1 (LONG) or PDH/R1 (SHORT) |
| S2 | `s2_breakout.py` | Strong M5 close beyond Daily P |
| S3 | `s3_break_retest.py` | Retest of a previously broken pivot (uses `PendingBreak` state) |
| S4 | `s4_sweep.py` | Wick beyond dilated zone + close inside |
| S5 | `s5_hot_zone.py` | S1 trigger filtered by multi-pivot confluence |
| S6 | `s6_sweet_spot.py` | S1 Daily on PDH/PDL/R1/S1 + narrow CPR Daily |

Each strategy is a pure `detect(snapshot, state) -> list[Signal]` — fully unit-tested with synthetic snapshots, replayable in walk-forward backtests (Plan 4) and consumable by the live cycle (Plan 3).

## Live mode (Plan 3)

```bash
cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
python -m agentic_trader.live.main
```

Runs continuously: every 5 minutes (UTC `:00:02 / :05:02 / …`) it fetches the watchlist, computes pivots, runs all enabled strategies, persists signals to SQLite, applies the priority + temporal dedup, and sends survivors to Telegram. SIGINT/SIGTERM trigger a graceful shutdown.

Healthcheck (for Docker): `python -m agentic_trader.observability.healthcheck` exits 0 iff the last cycle is < 10 minutes old.

## Project structure

See `docs/superpowers/plans/2026-05-05-plan-1-foundation-and-data-layer.md`
for the file layout and responsibilities.
