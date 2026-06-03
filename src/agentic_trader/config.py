from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    tv_username: str = ""
    tv_password: str = ""
    tv_sessionid: str = ""
    tv_sessionid_sign: str = ""
    log_level: str = "INFO"
    db_path: str = "./data/agent.db"
    notif_dedup_window_min: int = 30
    notif_dedup_within_atr: float = 0.10
    schedule_offset_seconds: int = 2
    min_rr_tp1: float = 1.5   # drop signals where TP1 R/R < this threshold
    enable_bias_gate: bool = True
    enable_legacy_signals: bool = False   # S1-S6 cycle archived; set true to re-enable
    scan_min_score: int = 55
    scan_dedup_window_min: int = 60
    scan_touch_lookback_bars: int = 3
    scan_buffer_frac: float = 0.25


class StrategyDefaults(BaseModel):
    model_config = ConfigDict(frozen=True)

    modes: list[str] = ["intraday", "swing"]
    strategies: list[str] = ["S1", "S2", "S3", "S4", "S5", "S6"]
    atr_dilation_mult: float = 0.15
    atr_dilation_cap_d_mult: float = 0.50
    confluence_threshold_atr_d: float = 0.30
    narrow_cpr_threshold: float = 0.50
    break_body_min_atr_m5: float = 0.50
    retest_window_m5_bars: int = 24
    candle_wick_min_ratio: float = 0.60
    candle_doji_body_max: float = 0.10


class SymbolConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    modes: list[str]
    strategies: list[str]


class WatchlistConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    defaults: StrategyDefaults
    watchlist: list[SymbolConfig]

    @classmethod
    def from_yaml(cls, path: str | Path) -> WatchlistConfig:
        raw = yaml.safe_load(Path(path).read_text())
        defaults = StrategyDefaults(**(raw.get("defaults") or {}))
        items = []
        for item in raw.get("watchlist") or []:
            items.append(
                SymbolConfig(
                    symbol=item["symbol"],
                    modes=item.get("modes", defaults.modes),
                    strategies=item.get("strategies", defaults.strategies),
                )
            )
        return cls(defaults=defaults, watchlist=items)
