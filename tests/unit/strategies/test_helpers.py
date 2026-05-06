import pytest

from agentic_trader.strategies.base import Strategy


def test_strategy_is_abstract():
    with pytest.raises(TypeError):
        Strategy()  # type: ignore[abstract]


def test_concrete_strategy_must_implement_detect():
    class Incomplete(Strategy):
        id = "Sx"
        name = "test"
        enabled_modes = {"intraday"}

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_concrete_strategy_can_be_instantiated():
    class Ok(Strategy):
        id = "Sx"
        name = "ok"
        enabled_modes = {"intraday"}

        def detect(self, snapshot, state):
            return []

    s = Ok()
    assert s.id == "Sx"
    assert s.detect(None, None) == []
