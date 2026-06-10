import os
import time

from agentic_trader.notify.capture import FileChartCapturer, NullCapturer


async def test_null_capturer_returns_none():
    assert await NullCapturer().capture("VANTAGE:XAUUSD") is None


async def test_file_capturer_picks_recent_symbol_file(tmp_path):
    now = time.time()
    older = tmp_path / "XAUUSD_100.png"
    older.write_bytes(b"a")
    os.utime(older, (now - 100, now - 100))
    newest = tmp_path / "XAUUSD_200.png"
    newest.write_bytes(b"b")
    os.utime(newest, (now - 10, now - 10))
    (tmp_path / "BTCUSD_300.png").write_bytes(b"c")  # other symbol
    cap = FileChartCapturer(capture_dir=str(tmp_path), max_age_s=3600)
    path = await cap.capture("VANTAGE:XAUUSD")
    assert path == str(newest)


async def test_file_capturer_ignores_stale(tmp_path):
    f = tmp_path / "XAUUSD_1.png"
    f.write_bytes(b"a")
    old = time.time() - 10_000
    os.utime(f, (old, old))
    cap = FileChartCapturer(capture_dir=str(tmp_path), max_age_s=600)
    assert await cap.capture("VANTAGE:XAUUSD") is None


async def test_file_capturer_none_when_no_match(tmp_path):
    cap = FileChartCapturer(capture_dir=str(tmp_path), max_age_s=600)
    assert await cap.capture("VANTAGE:XAUUSD") is None


async def test_file_capturer_missing_dir_returns_none():
    cap = FileChartCapturer(capture_dir="/no/such/dir", max_age_s=600)
    assert await cap.capture("VANTAGE:XAUUSD") is None
