from __future__ import annotations

import asyncio

import httpx

from agentic_trader.observability.logging import get_logger

log = get_logger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
DEFAULT_RETRY_DELAY_S = 3.0
DEFAULT_TIMEOUT_S = 10.0


class TelegramNotifier:
    """Plain-text sender for Telegram. One AsyncClient per instance."""

    def __init__(
        self,
        *,
        token: str,
        chat_id: str,
        client: httpx.AsyncClient | None = None,
        retry_delay_s: float = DEFAULT_RETRY_DELAY_S,
    ):
        self._token = token
        self._chat_id = chat_id
        self._client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S)
        self._retry_delay_s = retry_delay_s

    async def close(self) -> None:
        await self._client.aclose()

    async def send(self, text: str) -> bool:
        """Returns True on success, False on final failure (after 1 retry)."""
        url = f"{TELEGRAM_API_BASE}/bot{self._token}/sendMessage"
        body = {"chat_id": self._chat_id, "text": text}
        for attempt in (1, 2):
            try:
                resp = await self._client.post(url, json=body)
            except httpx.HTTPError as e:
                log.warning("telegram_send_network_error", attempt=attempt, error=str(e))
                if attempt == 2:
                    return False
                await asyncio.sleep(self._retry_delay_s)
                continue
            if resp.status_code == 200:
                return True
            if resp.status_code == 429:
                # Honour retry_after from the body (Telegram convention)
                try:
                    params = resp.json().get("parameters", {})
                    retry_after = float(params.get("retry_after", self._retry_delay_s))
                except Exception:
                    retry_after = self._retry_delay_s
                log.warning("telegram_send_rate_limited", retry_after=retry_after)
                if attempt == 2:
                    return False
                await asyncio.sleep(retry_after)
                continue
            if 500 <= resp.status_code < 600:
                log.warning("telegram_send_server_error", attempt=attempt, status=resp.status_code)
                if attempt == 2:
                    return False
                await asyncio.sleep(self._retry_delay_s)
                continue
            # 4xx (other) — don't retry
            log.error("telegram_send_client_error", status=resp.status_code, body=resp.text[:200])
            return False
        return False

    async def send_batch(self, texts: list[str]) -> list[tuple[str, bool]]:
        """Sends each text sequentially (Telegram bot has rate limits)."""
        results: list[tuple[str, bool]] = []
        for text in texts:
            ok = await self.send(text)
            results.append((text, ok))
        return results
