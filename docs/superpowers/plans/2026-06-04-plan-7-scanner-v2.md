# Scanner v2 Implementation Plan (Plan 7)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Single execution-TF scanner (default M5, configurable) scanning D/W/M zones together; episode dedup; tight-risk indicative levels with dual targets (HTF pivot + 2R). Reference: `docs/superpowers/specs/2026-06-04-scanner-v2-design.md`.

**Test:** `PYTHONPATH=src .venv/bin/python -m pytest <args>` · `.venv/bin/ruff check src tests`.

This refactors tested code; keep the suite green after each task.

---

## Plan 7a — Single execution-TF unification

### Task A1: config + build_snapshot exec_tf
- `config.py`: add `scan_exec_tf: str = "5"`, `scan_touch_ttl_min: int = 60`.
- `live/snapshot_builder.py`: `build_snapshot(*, fetcher, cache, symbol, now, exec_tf="5")`. Replace `fetch_m5(n_bars=50)` with `fetch_bars(symbol, exec_tf, n_bars=50)` for the execution series (`m5_bars`, `atr_m5`). When `exec_tf=="5"` behaviour is identical to today (fetch_bars("5") == fetch_m5). Pivots/atr_d unchanged.
- `.env.example`: `SCAN_EXEC_TF=5`, `SCAN_TOUCH_TTL_MIN=60`.
- Test `tests/unit/test_snapshot_builder.py` (live one) or new: build_snapshot with a fake fetcher records the exec timeframe code requested for the exec series (e.g. "5" default, "60" when exec_tf="60").

### Task A2: unified run_scan + scheduler + main
- `scanner/engine.py`: `run_scan(deps, *, now)` (drop `trigger_tf`). For each symbol: build snapshot (exec_tf from settings), exec_bars=snapshot.m5_bars; for tf in ("D","W","M") present: zones=build_zones(...); touches+=detect_touches(...); upsert with `expires_at=now+ttl` (ttl=settings.scan_touch_ttl_min*60). Then aggregate+score (build_alerts) and episode-dedup (Task B-dedup; until then keep the existing id-window dedup so the suite stays green) + notify.
- `live/scan_scheduler.py`: a single `scan` job. Cron from `scan_exec_tf`: "5"→minute="*/5"; "15"→"*/15"; "60"→minute=2 hourly. Helper `_cron_for(exec_tf)`. Digest jobs unchanged. Drop the per-cadence `_SCAN_BARS` use.
- `live/main.py`: build ScanDeps as before; `setup_scan_scheduler(scan_deps)` registers the single job.
- Tests: `test_scan_scheduler.py` → assert one job `scan` registered (cron `*/5`). Integration `test_run_scan.py` → adapt to `run_scan(deps, now=...)` (no trigger_tf); a single exec scan touching D + seeded W touch → ≥1 alert.

### Task A3: replay without cadence gating
- `backtest/scan_replay.py`: `replay_scan(..., base_key=...)` scans D/W/M every tick with the base bars (drop the `t.minute==0` / `hour in (0,12)` gating and `_SCAN_KEY`). Single TTL = `ttl_bars × base_interval` (e.g. 12 base bars) or a fixed `ttl_min`. Keep follow-through over base bars.
- Tests: `test_scan_replay.py` still green; assert D/W/M can all appear in members within a short synthetic run.

---

## Plan 7b — Episode dedup + tight indicative + dual-target follow-through

### Task B1: tight indicative + dual target (`scanner/scoring.py`)
- Replace `compute_indicative` with:
  `compute_indicative(setup, *, htf_pivot_set, buffer_frac) -> dict` →
  `{entry, stop, risk, target_htf, target_htf_label, rr_htf, target_2r, rr_2r}` per spec §5 (LONG entry=zone_low/stop=zone_low−buffer; SHORT entry=zone_high/stop=zone_high+buffer; buffer=buffer_frac×width; target_htf via `next_target(htf_pivot_set, direction, beyond=entry)`; target_2r=entry±2·risk; rr_2r=2.0).
- `scanner/engine.build_alerts`: use new compute_indicative (pass `htf_pivot_set=snapshot.pivots[htf]`, `buffer_frac`); emit even if target_htf is None; score rr = `indicative["rr_htf"] or 0.0`.
- Tests: rewrite `test_indicative.py` for the new keys; update `test_engine_logic.py` indicative assertions.

### Task B2: multi-target follow-through (`backtest/followthrough.py`)
- `simulate_followthrough(*, direction, entry, stop, targets: dict[str,float], future_bars, horizon_bars) -> FollowThrough` with `FollowThrough{outcomes: dict[str,str], mfe_r, mae_r, bars}`. Per target: TARGET if reached before stop, STOP, OPEN; STOP wins ties.
- Tests: rewrite `test_followthrough.py` for the dict API (htf TARGET while 2r OPEN, both STOP, etc.).

### Task B3: episode dedup
- `data/schema.sql`: `scan_active_episodes(alert_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, last_seen INTEGER NOT NULL)`.
- `data/repository.py`: `active_episode_ids(symbol) -> set[str]`, `set_active_episodes(symbol, ids: set[str], now)` (delete rows for symbol not in ids; upsert ids with last_seen=now).
- `scanner/engine.run_scan`: episode logic — `current = {scan_alert_id(a.setup) for a in alerts}`; `prev = await repo.active_episode_ids(symbol)`; emit `[a for a in alerts if id(a) not in prev]`; `await repo.set_active_episodes(symbol, current, now)`. (Replaces id-window dedup for triggering; keep `scan_notif_log` for send audit.)
- `backtest/scan_replay.replay_scan`: in-memory `active: set[str]`; emit ids not in active; `active = current` each tick.
- Tests: repo CRUD; engine integration (2 consecutive confluent scans → 1 alert; clear then reappear → 2); replay episode.

### Task B4: formatter dual target
- `notify/scan_formatter.render_scan_alert`: render entry/stop, `rr_htf` + `target_htf_label`, and `2R` target. Handle `target_htf=None`.
- Tests: update `test_scan_formatter.py`.

---

## Done when
- `pytest -q` + `ruff check src tests` clean; live scanner runs one exec-TF job scanning D/W/M; replay converges; alerts carry tight indicative + dual targets; episode dedup verified. Re-run XAUUSD 3-month H1 replay to compare.
