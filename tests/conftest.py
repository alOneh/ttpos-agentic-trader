import pytest


@pytest.fixture
def utc_now():
    from datetime import UTC, datetime
    return datetime.now(UTC)
