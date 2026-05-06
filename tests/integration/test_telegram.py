import httpx

from agentic_trader.notify.telegram import TelegramNotifier


def _make_notifier(transport: httpx.MockTransport) -> TelegramNotifier:
    client = httpx.AsyncClient(transport=transport, timeout=2.0)
    return TelegramNotifier(token="TEST_TOKEN", chat_id="CHAT_ID", client=client, retry_delay_s=0.01)


async def test_send_success():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert "TEST_TOKEN" in str(request.url)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    notifier = _make_notifier(httpx.MockTransport(handler))
    ok = await notifier.send("hello")
    assert ok is True
    assert len(calls) == 1
    body = calls[0].read().decode()
    assert "CHAT_ID" in body
    assert "hello" in body
    await notifier.close()


async def test_send_retries_once_on_5xx():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(503, json={"ok": False})
        return httpx.Response(200, json={"ok": True})

    notifier = _make_notifier(httpx.MockTransport(handler))
    ok = await notifier.send("retry-me")
    assert ok is True
    assert len(attempts) == 2
    await notifier.close()


async def test_send_returns_false_after_two_failures():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(503, json={"ok": False})

    notifier = _make_notifier(httpx.MockTransport(handler))
    ok = await notifier.send("doomed")
    assert ok is False
    assert len(attempts) == 2  # initial + 1 retry
    await notifier.close()


async def test_send_returns_false_on_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    notifier = _make_notifier(httpx.MockTransport(handler))
    ok = await notifier.send("network-down")
    assert ok is False
    await notifier.close()


async def test_send_batch_returns_per_signal_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        ok = "good" in body
        return httpx.Response(200 if ok else 503, json={"ok": ok})

    notifier = _make_notifier(httpx.MockTransport(handler))
    results = await notifier.send_batch(["good-a", "bad-b", "good-c"])
    assert results == [("good-a", True), ("bad-b", False), ("good-c", True)]
    await notifier.close()
