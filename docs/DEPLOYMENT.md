# Deployment — Dokploy

The agent runs as a single long-lived container. SQLite holds all persistent state, the watchlist is mounted as a config volume, secrets are injected as environment variables, and a Docker `HEALTHCHECK` triggers a restart if the cycle loop stalls.

## Prerequisites

- A Dokploy instance with Git access to this repository.
- A Telegram bot token + chat id where signals/digests will be posted.
- TradingView `sessionid` + `sessionid_sign` cookies (free TradingView account works; without them the agent runs anonymously and most symbols 404).

## Dokploy application setup

### 1. Create an application

In the Dokploy UI: **New → Application → Docker**.

| Field | Value |
|---|---|
| Source | Git (this repo) |
| Branch | `main` |
| Build path | `/` |
| Dockerfile | `Dockerfile` |

### 2. Volumes

Both are persistent. Create them in the **Volumes** tab.

| Volume name | Mount path | Purpose |
|---|---|---|
| `agentic-data` | `/app/data` | SQLite DB (`agent.db`), cycle health, pivots cache. Survives redeploys. |
| `agentic-config` | `/app/config` | Holds `watchlist.yaml`. After the first deploy, edit the file in this volume to change tracked symbols without rebuilding. |

The image ships a default `config/watchlist.yaml` at build time. On the first run, Dokploy mounts the (empty) `agentic-config` volume, which masks the baked-in file. Two options to seed:

- **Option A — let the agent crash once, then seed:** start the container, observe the `FileNotFoundError`, exec into it: `docker exec -it <container> cp config/watchlist.yaml /app/config/` (won't work because the volume already masks the source; instead seed by hand below).
- **Option B — seed before first run (recommended):** SSH to the Dokploy host, locate the volume (`docker volume inspect agentic-config`), copy `config/watchlist.yaml` from the repo into the volume path, then start the container. Or use Dokploy's file-browser if available.

Once seeded, you can edit the watchlist via SSH or Dokploy's file browser without rebuilding.

### 3. Environment variables

Set under **Environment**.

| Name | Required | Example | Notes |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | `12345:AAA...` | From @BotFather. |
| `TELEGRAM_CHAT_ID` | yes | `-100123456789` | Channel/group id. Get via @userinfobot. |
| `TV_SESSIONID` | recommended | (32-char hex) | Without it, anonymous mode → most symbols return empty. |
| `TV_SESSIONID_SIGN` | recommended | (long base64-ish string) | Pairs with `TV_SESSIONID`. |
| `LOG_LEVEL` | no | `INFO` | `DEBUG` for verbose, `WARNING` for quiet. |
| `MIN_RR_TP1` | no | `1.5` | Min reward/risk on TP1 to emit a signal. |
| `ENABLE_BIAS_GATE` | no | `true` | Multi-pivot stack bias filter. |
| `NOTIF_DEDUP_WINDOW_MIN` | no | `30` | De-dup window for repeat notifications. |
| `SCHEDULE_OFFSET_SECONDS` | no | `2` | Delay after each 5-min tick to let TV publish the closed bar. |

TradingView session cookies expire periodically. When the daily digest stops being delivered, refresh them in the UI and redeploy.

### 4. Build & deploy

- Hit **Deploy**. Dokploy clones the repo, runs `docker build`, and starts the container.
- First boot writes `/app/data/agent.db` (schema initialised by `Repository.init_schema`).
- Within 1–2 minutes the first 5-minute cycle fires (`event=cycle_start` in logs).

## Healthcheck behaviour

The Dockerfile declares:

```
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
  CMD python -m agentic_trader.observability.healthcheck
```

The CLI reads the `cycle_health` table from SQLite. It exits **0** when the most recent recorded cycle is younger than 10 minutes, **1** otherwise. With the policy above:

- `start-period=120s` — Dokploy treats the container as healthy for the first 2 minutes regardless (gives the agent time to record its first cycle).
- After that, an unhealthy result for 3 consecutive 60-second checks (≈3 min) marks the container unhealthy.
- Dokploy's default restart policy will then recreate it. The most common cause of unhealthy state is a dead TradingView WebSocket; a restart re-handshakes and recovers.

## Logs

Structlog writes JSON lines to stdout. Dokploy's log viewer captures them. Look for:

- `event=starting` — process boot.
- `event=tv_auth anonymous=false` — TradingView credentials accepted.
- `event=scheduler_started n_symbols=N` — APScheduler armed with the trading cycle + 9 digest jobs.
- `event=cycle_start` / `event=cycle_done` — 5-minute heartbeat.
- `event=digest_sent` — a digest message was published.

Filter on `level=error` to surface fetch failures or bus crashes.

## Updating

For code changes:

1. Push to `main`.
2. Hit **Deploy** in Dokploy → fresh build & rolling restart.
3. The persistent volumes survive the restart; the DB schema is idempotent (`CREATE TABLE IF NOT EXISTS`).

For watchlist-only changes: edit `/app/config/watchlist.yaml` via SSH or Dokploy's file browser and restart the container (no rebuild). The agent reads the file on boot.

## Resource sizing

The agent is lightweight: ~50 MB RAM steady state, near-zero CPU between 5-minute ticks. A 512 MB container is comfortable.

## Local test (optional)

To verify the image before pushing:

```bash
docker build -t agentic-trader:test .

docker run --rm \
  -e TELEGRAM_BOT_TOKEN=<your-token> \
  -e TELEGRAM_CHAT_ID=<your-chat> \
  -e TV_SESSIONID=<your-session> \
  -e TV_SESSIONID_SIGN=<your-sign> \
  -v "$PWD/data:/app/data" \
  -v "$PWD/config:/app/config" \
  agentic-trader:test
```

Stop with `Ctrl+C`; the signal handler in `live/main.py` triggers a clean shutdown (`event=shutdown_initiated`, `event=shutdown_complete`).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `FileNotFoundError: config/watchlist.yaml` on boot | Volume `agentic-config` is empty | Seed it from the repo's `config/watchlist.yaml` (see §2 above). |
| `tv_auth anonymous=true` despite cookies set | Env vars misnamed | Variables are `TV_SESSIONID` and `TV_SESSIONID_SIGN` — no underscore in `SESSIONID`. |
| `symbols_failed=N` in every cycle | Anonymous auth or expired TV session | Refresh `TV_SESSIONID*` cookies and redeploy. |
| Healthcheck flaps to unhealthy after hours of uptime | Dead TV WebSocket | Healthcheck-triggered restart is the intended recovery. If frequent, investigate TV rate limits. |
| No digest at expected time | Cron timezone | All cron triggers run in UTC. Check container time: `docker exec -it <container> date -u`. |
