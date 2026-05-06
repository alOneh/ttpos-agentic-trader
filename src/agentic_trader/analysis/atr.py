from __future__ import annotations

import pandas as pd

from agentic_trader.domain.pivots import TF


def atr(df: pd.DataFrame, period: int = 14) -> float:
    """Wilder's ATR over `period` bars on a DataFrame with high/low/close columns.

    Returns the most recent ATR value. Raises ValueError if fewer than period+1 bars.
    """
    if len(df) < period + 1:
        raise ValueError(f"need at least {period + 1} bars, got {len(df)}")
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    # Wilder smoothing = EMA with alpha=1/period
    val = tr.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    return float(val)


def dilation_for(
    *,
    pivot_tf: TF,
    atr_pivot_tf: float,
    atr_d: float,
    mult: float = 0.15,
    cap_d_mult: float = 0.50,
) -> float:
    """Buffer applied symmetrically to a pivot value.

    For W/M, the buffer is capped at `cap_d_mult * atr_d` to avoid huge zones.
    """
    base = mult * atr_pivot_tf
    if pivot_tf in ("W", "M"):
        cap = cap_d_mult * atr_d
        return min(base, cap)
    return base
