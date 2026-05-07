from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from tradingview_api.models.ohlcv import Period

from agentic_trader.analysis.atr import atr as atr_fn
from agentic_trader.analysis.atr import dilation_for
from agentic_trader.analysis.pivots_calc import compute_pivots
from agentic_trader.backtest.history import SymbolHistory
from agentic_trader.domain.pivots import TF, PivotSet
from agentic_trader.domain.snapshot import MarketSnapshot

ATR_PERIOD = 14
M5_LOOKBACK_DEFAULT = 50

# Map TV TF key → domain TF and TV interval seconds
_TV_TO_DOMAIN: dict[str, TF] = {"240": "4H", "1D": "D", "1W": "W", "1M": "M"}
_TF_SECONDS = {"4H": 4 * 3600, "D": 86400, "W": 7 * 86400, "M": 30 * 86400}


def _df(bars: list[Period]) -> pd.DataFrame:
    return pd.DataFrame([{"high": b.high, "low": b.low, "close": b.close} for b in bars])


def _bars_up_to(bars: list[Period], t_ts: int) -> list[Period]:
    return [b for b in bars if b.time <= t_ts]


def build_snapshot_at(
    history: SymbolHistory,
    t: datetime,
    *,
    m5_lookback: int = M5_LOOKBACK_DEFAULT,
) -> MarketSnapshot:
    """Build a MarketSnapshot reflecting state at time t using pre-fetched history."""
    t_ts = int(t.timestamp())

    m5_window = _bars_up_to(history.m5(), t_ts)
    if not m5_window:
        raise ValueError(f"no M5 bars before {t.isoformat()} for {history.symbol}")
    m5_bars = m5_window[-m5_lookback:]

    # ATR_D first (used by dilation).  Higher-TF bars are used as-is from the
    # pre-fetched history — the runner has already loaded only historical data.
    daily_window = history.bars["1D"]
    df_d = _df(daily_window)
    atr_d = atr_fn(df_d, period=ATR_PERIOD) if len(df_d) >= ATR_PERIOD + 1 else 0.0

    df_m5 = _df(m5_window)
    atr_m5 = atr_fn(df_m5, period=ATR_PERIOD) if len(df_m5) >= ATR_PERIOD + 1 else 0.0

    pivots: dict[TF, PivotSet] = {}
    for tv_key, tf in _TV_TO_DOMAIN.items():
        window = history.bars[tv_key]
        if len(window) < 22:
            # Skip this TF — runner ensures sufficient history; if not, snapshot will lack this TF
            continue
        last_closed = window[-1]
        # session_end conservatively set to last_closed.time + interval (next bar boundary)
        session_end_ts = last_closed.time + _TF_SECONDS[tf]
        last_20 = window[-21:-1]  # 20 bars BEFORE the last closed (so 21 total → exclude last)
        widths = []
        for b in last_20:
            P = (b.high + b.low + b.close) / 3.0
            BC = (b.high + b.low) / 2.0
            TC = 2 * P - BC
            widths.append(abs(TC - BC))
        cpr_width_avg_20 = sum(widths) / len(widths) if widths else 0.0
        # ATR for this TF
        df_tf = _df(window)
        atr_tf = atr_fn(df_tf, period=ATR_PERIOD) if len(df_tf) >= ATR_PERIOD + 1 else 0.0
        dilation = dilation_for(pivot_tf=tf, atr_pivot_tf=atr_tf, atr_d=atr_d)
        pivots[tf] = compute_pivots(
            symbol=history.symbol, timeframe=tf,
            pdh=last_closed.high, pdl=last_closed.low, pdc=last_closed.close,
            session_end=datetime.fromtimestamp(session_end_ts, tz=UTC),
            cpr_width_avg_20=cpr_width_avg_20, dilation=dilation,
        )

    return MarketSnapshot(
        symbol=history.symbol, cycle_time=t, m5_bars=m5_bars,
        pivots=pivots, atr_m5=atr_m5, atr_d=atr_d,
        market_info=history.info,
    )
