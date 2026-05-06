from agentic_trader.config import StrategyDefaults, SymbolConfig, WatchlistConfig
from agentic_trader.strategies.registry import ALL_STRATEGIES, enabled_for


def test_all_strategies_contains_six():
    ids = {s.id for s in ALL_STRATEGIES}
    assert ids == {"S1", "S2", "S3", "S4", "S5", "S6"}


def test_all_strategies_have_unique_ids():
    ids = [s.id for s in ALL_STRATEGIES]
    assert len(ids) == len(set(ids))


def test_enabled_for_symbol_with_default_config():
    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(symbol="VANTAGE:XAUUSD", modes=["intraday", "swing"],
                                 strategies=["S1", "S2", "S3", "S4", "S5", "S6"])],
    )
    enabled = enabled_for("VANTAGE:XAUUSD", cfg)
    assert {s.id for s in enabled} == {"S1", "S2", "S3", "S4", "S5", "S6"}


def test_enabled_for_symbol_with_subset_strategies():
    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(symbol="VANTAGE:DJ30", modes=["intraday"],
                                 strategies=["S1", "S3"])],
    )
    enabled = enabled_for("VANTAGE:DJ30", cfg)
    assert {s.id for s in enabled} == {"S1", "S3"}


def test_enabled_for_unknown_symbol_returns_empty():
    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(symbol="VANTAGE:XAUUSD", modes=["intraday"],
                                 strategies=["S1"])],
    )
    assert enabled_for("UNKNOWN:Y", cfg) == []
