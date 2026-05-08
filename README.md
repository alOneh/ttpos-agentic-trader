# Agentic Trader

Multi-timeframe pivot scanner that detects trading setups on M5 and notifies via Telegram. See `docs/superpowers/specs/2026-05-05-agentic-trader-design.md` for the full design.

## Status

**Plan 1 (Foundation + Data layer) — implemented.**
**Plan 2 (Strategies S1-S6) — implemented.**
**Plan 3 (Live MVP + Telegram) — implemented.**
**Plan 4 (Backtest V2) — implemented.**
**Plan 5 (Scalping mode / 4H trigger) — implemented.**

Plan 6 (Deployment) — pending.

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

## Backtest (Plan 4)

```bash
python -m agentic_trader.backtest.cli \
    --symbol VANTAGE:XAUUSD \
    --from 2025-11-01 --to 2025-11-30 \
    --strategies S1,S2,S3,S4,S5,S6 \
    --partial-take 33,33,34 \
    --output backtest_xauusd_2025_11.json
```

Walk-forward replay over historical M5 bars. Each detected setup opens a `SimulatedTrade` with the strategy's spec'd SL + multi-TP ladder. Subsequent bars apply SL/TP fills (priority SL > TP1 > TP2 > TP3 within a bar). Output JSON includes per-trade events (entry, TPs, SL, MFE/MAE in R, exit time) and per-strategy metrics (win rate, expectancy in R, Sharpe-on-R, max drawdown).

V2.0 limitations: no slippage, fill at exact level price. Bar-internal sequencing is conservative (SL assumed first when range covers both SL and TP). Add slippage model in a later iteration if needed.

## Modes

Three independent trading modes coexist:

| Mode | Pivot TFs | Rationale |
|---|---|---|
| `scalp` | 4H | Short holding horizons, tight SL / close TPs |
| `intraday` | Daily | Standard intra-day setups |
| `swing` | Weekly + Monthly | Multi-day to multi-week holds |

Per symbol, choose modes via `config/watchlist.yaml`:

```yaml
watchlist:
  - symbol: VANTAGE:XAUUSD
    modes: [scalp, intraday]   # active only on these
  - symbol: VANTAGE:DJ30
    modes: [intraday]
```

The default is `[intraday]`. Strategies emit all modes they support;
the orchestrator filters by `modes` before persistence and Telegram.

S6 Sweet Spot is the only strategy locked to a specific mode (Daily/intraday
— its narrow-CPR-Daily filter is structurally Daily-tied).

## Signal quality filter

Signals with `TP1 R/R < MIN_RR_TP1` (default 1.5) are dropped at the orchestrator
layer — they're never persisted, never sent to Telegram. This addresses scalp-mode
signals where 4H pivots are tight and SL eats most of the risk budget. Override via
`.env`:

```
MIN_RR_TP1=1.5   # raise to 2.0 for stricter quality, lower to 1.0 for more flow
```

In backtest mode, set `BacktestConfig.min_rr_tp1` (default `None` = no filter, so
existing baseline backtests still see all signals).

## Project structure

See `docs/superpowers/plans/2026-05-05-plan-1-foundation-and-data-layer.md`
for the file layout and responsibilities.
