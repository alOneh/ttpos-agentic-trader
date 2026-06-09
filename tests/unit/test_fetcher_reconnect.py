from agentic_trader.data.fetcher import TVFetcher


class _FakeClient:
    def __init__(self, connected=True):
        self.is_connected = connected
        self.connects = 0
        self.closes = 0

    async def connect(self):
        self.connects += 1
        self.is_connected = True

    async def close(self):
        self.closes += 1
        self.is_connected = False


async def test_reconnect_closes_then_connects():
    c = _FakeClient(connected=False)
    f = TVFetcher(client=c)
    await f.reconnect()
    assert c.closes == 1 and c.connects == 1 and c.is_connected is True


async def test_ensure_connected_reconnects_when_down():
    c = _FakeClient(connected=False)
    f = TVFetcher(client=c)
    await f.ensure_connected()
    assert c.connects == 1 and c.is_connected is True


async def test_ensure_connected_noop_when_up():
    c = _FakeClient(connected=True)
    f = TVFetcher(client=c)
    await f.ensure_connected()
    assert c.connects == 0 and c.closes == 0


async def test_reconnect_noop_without_client():
    f = TVFetcher(client=None)
    await f.reconnect()  # must not raise
    await f.ensure_connected()  # must not raise
