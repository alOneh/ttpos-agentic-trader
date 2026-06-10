from unittest.mock import MagicMock

from agentic_trader.config import Settings
from agentic_trader.live.scheduler import setup_scheduler


def _deps(enable_legacy: bool) -> MagicMock:
    deps = MagicMock()
    deps.settings = Settings(enable_legacy_signals=enable_legacy)
    return deps


def test_trading_cycle_not_registered_by_default():
    deps = _deps(enable_legacy=False)
    scheduler = setup_scheduler(deps, digest_deps=None)
    assert scheduler.get_job("trading_cycle") is None


def test_trading_cycle_registered_when_flag_on():
    deps = _deps(enable_legacy=True)
    scheduler = setup_scheduler(deps, digest_deps=None)
    assert scheduler.get_job("trading_cycle") is not None
