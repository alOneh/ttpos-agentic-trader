CREATE TABLE IF NOT EXISTS ohlcv_cache (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    bar_time INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (symbol, timeframe, bar_time)
);

CREATE TABLE IF NOT EXISTS pivots_cache (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    session_end INTEGER NOT NULL,
    pivot_set_json TEXT NOT NULL,
    PRIMARY KEY (symbol, timeframe)
);

CREATE TABLE IF NOT EXISTS pending_breaks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    pivot_tag TEXT NOT NULL,
    pivot_tf TEXT NOT NULL,
    pivot_value REAL NOT NULL,
    direction TEXT NOT NULL,
    break_price REAL NOT NULL,
    break_time INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pending_breaks_expires ON pending_breaks(expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_breaks_unique
    ON pending_breaks(symbol, pivot_tag, pivot_tf, direction);

CREATE TABLE IF NOT EXISTS signals_log (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL,
    mode TEXT NOT NULL,
    cycle_time INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_cycle ON signals_log(cycle_time DESC);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_strat
    ON signals_log(symbol, strategy, direction, cycle_time DESC);

CREATE TABLE IF NOT EXISTS notif_log (
    signal_id TEXT PRIMARY KEY,
    sent_at INTEGER NOT NULL,
    status TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS cycle_health (
    cycle_time INTEGER PRIMARY KEY,
    duration_ms INTEGER NOT NULL,
    symbols_ok INTEGER NOT NULL,
    symbols_failed INTEGER NOT NULL,
    signals_emitted INTEGER NOT NULL,
    signals_notified INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cycle_health_time ON cycle_health(cycle_time DESC);

CREATE TABLE IF NOT EXISTS touches (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,          -- "D","W","M"
    zone_kind TEXT NOT NULL,          -- "level" | "bracket"
    tag TEXT NOT NULL,                -- "S1","R2","PDL-S1",…
    zone_low REAL NOT NULL,
    zone_high REAL NOT NULL,
    side TEXT NOT NULL,
    direction TEXT NOT NULL,
    bar_time INTEGER NOT NULL,
    seen_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    PRIMARY KEY (symbol, timeframe, tag, bar_time)
);
CREATE INDEX IF NOT EXISTS idx_touches_active ON touches(symbol, expires_at);

CREATE TABLE IF NOT EXISTS scan_alerts (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    score INTEGER NOT NULL,
    tf_count INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scan_alerts_time ON scan_alerts(created_at DESC);

CREATE TABLE IF NOT EXISTS scan_notif_log (
    alert_id TEXT PRIMARY KEY,
    sent_at INTEGER NOT NULL,
    status TEXT NOT NULL,             -- "sent" | "failed" | "suppressed_by_window"
    error TEXT
);
