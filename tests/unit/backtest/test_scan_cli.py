from agentic_trader.backtest.scan_cli import summarize_text
from agentic_trader.backtest.scan_replay import ReplayResult


def test_summarize_text_renders_key_numbers():
    result = ReplayResult(
        config={"symbol": "VANTAGE:XAUUSD", "start": "2026-03-04", "end": "2026-06-04",
                "min_score": 0, "horizon_bars": 1440},
        alerts=[],
        summary={"n_alerts": 3, "by_band": {"low": 2, "monitor": 1},
                 "by_direction": {"LONG": 2, "SHORT": 1}, "by_month": {"2026-05": 3},
                 "n_target": 1, "n_stop": 1, "n_open": 1, "win_rate": 0.5,
                 "avg_mfe_r": 1.2, "avg_mae_r": 0.7},
    )
    text = summarize_text(result)
    assert "VANTAGE:XAUUSD" in text
    assert "n_alerts" in text
    assert "3" in text
    assert "win" in text.lower()
