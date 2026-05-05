import pytest

@pytest.fixture
def utc_now():
    from datetime import datetime, UTC
    return datetime.now(UTC)
