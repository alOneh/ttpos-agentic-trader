from unittest.mock import AsyncMock

import httpx
from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.config import (
    Settings,
    StrategyDefaults,
    SymbolConfig,
    WatchlistConfig,
)
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.live.cycle import Deps, run_cycle
from agentic_trader.notify.dedup import NotifDedupPolicy
from agentic_trader.notify.telegram import TelegramNotifier


def _bars_with_pdl_hammer(start_ts: int, n: int, step: int):
    """Build n bars where the last one is a hammer that touches the synthetic PDL=99.

    Daily synthetic bars have PDH=101, PDL=99, PDC=100 → PDL pivot = 99.
    The hammer bar low=98.9 enters the dilated PDL zone, with body close 99.6 in
    the upper third → triggers S1 LONG.
    """
    bars = [
        Period(time=start_ts + step * i, open=100.5, high=100.8, low=100.2, close=100.5, volume=1.0)
        for i in range(n - 1)
    ]
    bars.append(Period(
        time=start_ts + step * (n - 1),
        open=99.7, high=99.8, low=98.9, close=99.6, volume=1.0,
    ))
    return bars


def _bars_pivot_set(start_ts: int, n: int, step: int):
    """22 bars with PDH=101, PDL=99, PDC=100 → P=100, S1=99, R1=101 (tight pivots near hammer)."""
    return [
        Period(time=start_ts + step * i, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
        for i in range(n)
    ]


async def test_cycle_end_to_end_emits_signals_and_calls_telegram(tmp_path, monkeypatch):
    base = 1700000000

    def fake_fetch(*, symbol, timeframe, n_bars, client):
        info = MarketInfo(name=symbol.split(":")[-1], pricescale=100.0)
        if timeframe == "5":
            return OHLCVResult(
                symbol=symbol, timeframe=timeframe, info=info,
                periods=_bars_with_pdl_hammer(base, n_bars, 300),
            )
        seconds = {"240": 14400, "1D": 86400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe, info=info,
            periods=_bars_pivot_set(base, n_bars, seconds),
        )

    fetcher = TVFetcher(client=None, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))

    sent_messages = []

    def telegram_handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        sent_messages.append(body)
        return httpx.Response(200, json={"ok": True})

    notifier = TelegramNotifier(
        token="T", chat_id="C",
        client=httpx.AsyncClient(transport=httpx.MockTransport(telegram_handler), timeout=2.0),
    )

    repo = Repository(db_path=tmp_path / "cycle.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    settings = Settings(
        telegram_bot_token="T", telegram_chat_id="C",
        db_path=str(tmp_path / "cycle.db"),
        notif_dedup_window_min=30, notif_dedup_within_atr=0.10,
    )
    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(
            symbol="VANTAGE:XAUUSD", modes=["intraday", "swing"],
            strategies=["S1", "S2", "S3", "S4", "S5", "S6"],
        )],
    )
    dedup = NotifDedupPolicy(window_min=30, within_atr=0.10)

    deps = Deps(settings=settings, config=cfg, repo=repo, fetcher=fetcher,
                cache=cache, notifier=notifier, dedup=dedup)

    report = await run_cycle(deps)

    assert report.symbols_ok == 1
    assert report.symbols_failed == 0
    # We expect at least one signal (S1 LONG on PDL=99 from the hammer bar low=98.9).
    # If the synthetic data calibration drifts in a future refactor, relax this to >= 0
    # and rely on the cycle_health + Telegram-POST-count assertions below.
    assert report.signals_emitted >= 1
    # Telegram receives one POST per signal that passed dedup
    assert len(sent_messages) == report.signals_notified
    if report.signals_notified > 0:
        assert all("VANTAGE:XAUUSD" in body for body in sent_messages)

    # Persisted
    saved = await repo.load_signals_since(report.cycle_time)
    assert len(saved) == report.signals_emitted
    health = await repo.recent_cycle_health(limit=1)
    assert health[0]["signals_emitted"] == report.signals_emitted
    assert health[0]["signals_notified"] == report.signals_notified

    await notifier.close()
    await repo.close()
