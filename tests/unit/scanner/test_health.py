from datetime import UTC, datetime
from unittest.mock import MagicMock

from agentic_trader.config import Settings
from agentic_trader.scanner.engine import ScanDeps, _update_health

NOW = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)


class _RecNotifier:
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(text)
        return True


def _deps(notifier):
    return ScanDeps(settings=Settings(), repo=MagicMock(), fetcher=MagicMock(),
                    cache=MagicMock(), notifier=notifier, symbols=["X", "Y"])


async def test_health_warns_after_threshold_then_recovers():
    n = _RecNotifier()
    deps = _deps(n)
    # 2 all-failed cycles → no warning yet (threshold is 3)
    await _update_health(deps, symbols_ok=0, total=2, now=NOW)
    await _update_health(deps, symbols_ok=0, total=2, now=NOW)
    assert n.sent == []
    # 3rd consecutive all-failed cycle → one warning
    await _update_health(deps, symbols_ok=0, total=2, now=NOW)
    assert len(n.sent) == 1 and "⚠️" in n.sent[0]
    # still failing → no duplicate warning
    await _update_health(deps, symbols_ok=0, total=2, now=NOW)
    assert len(n.sent) == 1
    # a successful cycle → recovery message, counter reset
    await _update_health(deps, symbols_ok=1, total=2, now=NOW)
    assert len(n.sent) == 2 and "rétabli" in n.sent[1]
    assert deps.health == {"fails": 0, "alerted": False}


async def test_health_quiet_when_partial_success():
    n = _RecNotifier()
    deps = _deps(n)
    # at least one symbol ok every cycle → never warns
    for _ in range(5):
        await _update_health(deps, symbols_ok=1, total=2, now=NOW)
    assert n.sent == []
