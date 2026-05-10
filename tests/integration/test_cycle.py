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
        min_rr_tp1=0.0,  # disable R/R filter — this test covers Telegram dispatch, not R/R
        enable_bias_gate=False,  # disable bias gate — test pre-dates bias gate feature
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


async def test_cycle_filters_by_per_symbol_modes(tmp_path):
    """Verify sym_cfg.modes is enforced at the cycle level."""
    base = 1700000000

    def fake_fetch(*, symbol, timeframe, n_bars, client):
        info = MarketInfo(name=symbol.split(":")[-1], pricescale=100.0)
        if timeframe == "5":
            bars = [
                Period(time=base + 300 * i, open=100.5, high=100.8, low=100.2, close=100.5, volume=1.0)
                for i in range(289)
            ]
            bars.append(Period(time=base + 300 * 289, open=99.7, high=99.8, low=98.9, close=99.6, volume=1.0))
            return OHLCVResult(symbol=symbol, timeframe="5", info=info, periods=bars)
        seconds = {"240": 14400, "1D": 86400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe, info=info,
            periods=[
                Period(time=base + seconds * i, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
                for i in range(30)
            ],
        )

    fetcher = TVFetcher(client=None, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))

    sent_messages = []

    def telegram_handler(request):
        sent_messages.append(request.read().decode())
        return httpx.Response(200, json={"ok": True})

    notifier = TelegramNotifier(
        token="T", chat_id="C",
        client=httpx.AsyncClient(transport=httpx.MockTransport(telegram_handler), timeout=2.0),
    )
    repo = Repository(db_path=tmp_path / "modes.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    settings = Settings(
        telegram_bot_token="T", telegram_chat_id="C",
        db_path=str(tmp_path / "modes.db"),
        notif_dedup_window_min=30, notif_dedup_within_atr=0.10,
        enable_bias_gate=False,  # disable bias gate — test pre-dates bias gate feature
    )
    # Symbol restricted to scalp only — even though strategies emit intraday too,
    # only scalp signals should land in signals_log.
    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(
            symbol="VANTAGE:XAUUSD", modes=["scalp"],
            strategies=["S1", "S2", "S3", "S4", "S5", "S6"],
        )],
    )
    dedup = NotifDedupPolicy(window_min=30, within_atr=0.10)
    deps = Deps(settings=settings, config=cfg, repo=repo, fetcher=fetcher,
                cache=cache, notifier=notifier, dedup=dedup)

    report = await run_cycle(deps)

    saved = await repo.load_signals_since(report.cycle_time)
    # All retained signals must be scalp mode
    assert all(s.mode == "scalp" for s in saved), \
        f"non-scalp signal leaked: {[s.mode for s in saved if s.mode != 'scalp']}"
    await notifier.close()
    await repo.close()


async def test_cycle_filters_low_rr_signals(tmp_path):
    """Verify signals with TP1 R/R < min_rr_tp1 are dropped."""
    base = 1700000000

    def fake_fetch(*, symbol, timeframe, n_bars, client):
        info = MarketInfo(name=symbol.split(":")[-1], pricescale=100.0)
        if timeframe == "5":
            bars = [
                Period(time=base + 300 * i, open=100.5, high=100.8, low=100.2, close=100.5, volume=1.0)
                for i in range(289)
            ]
            bars.append(Period(time=base + 300 * 289, open=99.7, high=99.8, low=98.9, close=99.6, volume=1.0))
            return OHLCVResult(symbol=symbol, timeframe="5", info=info, periods=bars)
        seconds = {"240": 14400, "1D": 86400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe, info=info,
            periods=[
                Period(time=base + seconds * i, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
                for i in range(30)
            ],
        )

    fetcher = TVFetcher(client=None, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))

    def telegram_handler(request):
        return httpx.Response(200, json={"ok": True})
    notifier = TelegramNotifier(
        token="T", chat_id="C",
        client=httpx.AsyncClient(transport=httpx.MockTransport(telegram_handler), timeout=2.0),
    )
    repo = Repository(db_path=tmp_path / "rr.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    # Set an absurdly high threshold (10) so all signals are filtered out
    settings = Settings(
        telegram_bot_token="T", telegram_chat_id="C",
        db_path=str(tmp_path / "rr.db"),
        notif_dedup_window_min=30, notif_dedup_within_atr=0.10,
        min_rr_tp1=10.0,
    )
    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(
            symbol="VANTAGE:XAUUSD", modes=["intraday", "swing", "scalp"],
            strategies=["S1", "S2", "S3", "S4", "S5", "S6"],
        )],
    )
    dedup = NotifDedupPolicy(window_min=30, within_atr=0.10)
    deps = Deps(settings=settings, config=cfg, repo=repo, fetcher=fetcher,
                cache=cache, notifier=notifier, dedup=dedup)

    report = await run_cycle(deps)
    # With min_rr_tp1=10, no signal should pass
    assert report.signals_emitted == 0
    await notifier.close()
    await repo.close()


async def test_cycle_bias_gate_blocks_against_trend_signals(tmp_path):
    """Verify enable_bias_gate=True drops LONG signals when price is far below all pivots."""
    base = 1700000000

    # Synthetic: M5 price around 50, Daily/Weekly/Monthly bars around 100 → bias=strong_sell.
    # Hammer at price ~50, but stack bias is strong_sell → no LONG signal should survive.
    def fake_fetch(*, symbol, timeframe, n_bars, client):
        info = MarketInfo(name=symbol.split(":")[-1], pricescale=100.0)
        if timeframe == "5":
            bars = [
                Period(time=base + 300 * i, open=50.5, high=50.8, low=50.2, close=50.5, volume=1.0)
                for i in range(289)
            ]
            # Hammer at 50: low=48.9, close=49.6
            bars.append(Period(time=base + 300 * 289, open=49.7, high=49.8, low=48.9, close=49.6, volume=1.0))
            return OHLCVResult(symbol=symbol, timeframe="5", info=info, periods=bars)
        seconds = {"240": 14400, "1D": 86400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe, info=info,
            periods=[
                Period(time=base + seconds * i, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
                for i in range(30)
            ],
        )

    fetcher = TVFetcher(client=None, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))

    def telegram_handler(request):
        return httpx.Response(200, json={"ok": True})

    notifier = TelegramNotifier(
        token="T", chat_id="C",
        client=httpx.AsyncClient(transport=httpx.MockTransport(telegram_handler), timeout=2.0),
    )
    repo = Repository(db_path=tmp_path / "bias.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    settings = Settings(
        telegram_bot_token="T", telegram_chat_id="C",
        db_path=str(tmp_path / "bias.db"),
        notif_dedup_window_min=30, notif_dedup_within_atr=0.10,
        min_rr_tp1=0.0,         # disable R/R filter for this test
        enable_bias_gate=True,  # the variable under test
    )
    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(
            symbol="VANTAGE:XAUUSD", modes=["intraday"],
            strategies=["S1", "S2", "S3", "S4", "S5", "S6"],
        )],
    )
    dedup = NotifDedupPolicy(window_min=30, within_atr=0.10)
    deps = Deps(settings=settings, config=cfg, repo=repo, fetcher=fetcher,
                cache=cache, notifier=notifier, dedup=dedup)

    report = await run_cycle(deps)
    saved = await repo.load_signals_since(report.cycle_time)
    long_signals = [s for s in saved if s.direction == "LONG"]
    assert long_signals == [], \
        f"bias gate failed to block counter-trend long: {[s.id for s in long_signals]}"
    await notifier.close()
    await repo.close()
