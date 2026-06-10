import httpx
import pytest

from agentic_trader.notify.telegram import TelegramNotifier


class _Capture:
    def __init__(self):
        self.url = None
        self.data = None


@pytest.fixture
def cap():
    return _Capture()


def _client(cap, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        cap.url = str(request.url)
        cap.data = request.content  # multipart body bytes
        return httpx.Response(status)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_send_photo_posts_to_sendphoto(tmp_path, cap):
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
    notifier = TelegramNotifier(token="T", chat_id="C", client=_client(cap))
    ok = await notifier.send_photo(caption="hello", image_path=str(img))
    assert ok is True
    assert cap.url.endswith("/botT/sendPhoto")
    assert b"hello" in cap.data            # caption present in multipart
    assert b"fakepng" in cap.data          # file bytes present


async def test_send_photo_returns_false_on_missing_file(tmp_path, cap):
    notifier = TelegramNotifier(token="T", chat_id="C", client=_client(cap))
    ok = await notifier.send_photo(caption="x", image_path=str(tmp_path / "nope.png"))
    assert ok is False
    assert cap.url is None  # never attempted the HTTP call
