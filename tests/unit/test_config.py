from agentic_trader.config import Settings, WatchlistConfig


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("DB_PATH", "/tmp/foo.db")
    s = Settings()
    assert s.telegram_bot_token == "tok"
    assert s.telegram_chat_id == "chat"
    assert s.db_path == "/tmp/foo.db"
    assert s.notif_dedup_window_min == 30  # default
    assert s.log_level == "INFO"


def test_watchlist_yaml_parsing(tmp_path):
    (tmp_path / "watchlist.yaml").write_text(
        """
defaults:
  modes: [intraday, swing]
  strategies: [S1, S2, S3, S4, S5, S6]
  atr_dilation_mult: 0.07
  atr_dilation_cap_d_mult: 0.50
  confluence_threshold_atr_d: 0.30
  narrow_cpr_threshold: 0.50
  break_body_min_atr_m5: 0.50
  retest_window_m5_bars: 24
  candle_wick_min_ratio: 0.60
  candle_doji_body_max: 0.10

watchlist:
  - symbol: VANTAGE:XAUUSD
  - symbol: VANTAGE:DJ30
    strategies: [S1, S3]
"""
    )
    cfg = WatchlistConfig.from_yaml(tmp_path / "watchlist.yaml")
    assert len(cfg.watchlist) == 2
    assert cfg.watchlist[0].symbol == "VANTAGE:XAUUSD"
    # Defaults inherited
    assert cfg.watchlist[0].strategies == ["S1", "S2", "S3", "S4", "S5", "S6"]
    # Override applied
    assert cfg.watchlist[1].strategies == ["S1", "S3"]
    assert cfg.defaults.atr_dilation_mult == 0.07
