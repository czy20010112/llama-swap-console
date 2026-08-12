from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx


class SwapUnavailable(Exception):
    """llama-swap could not be reached."""


class SwapReadTimeout(SwapUnavailable):
    """llama-swap did not finish a lifecycle request before its read deadline."""


class SwapResponseError(Exception):
    """llama-swap returned a non-success response."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body[:1000]
        super().__init__(f"llama-swap returned HTTP {status}: {self.body}")


class LlamaSwapClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._request_timeout = httpx.Timeout(3.0)
        self._event_timeout = httpx.Timeout(
            connect=3.0, read=None, write=3.0, pool=3.0
        )

    async def models(self) -> Any:
        return await self._request("GET", "/v1/models")

    async def running(self) -> Any:
        return await self._request("GET", "/running")

    async def load(self, model_id: str) -> Any:
        encoded = quote(model_id, safe="")
        return await self._request(
            "GET", f"/upstream/{encoded}/", timeout=httpx.Timeout(10.0)
        )

    async def unload(self, model_id: str) -> Any:
        encoded = quote(model_id, safe="")
        return await self._request("POST", f"/api/models/unload/{encoded}")

    async def unload_all(self) -> Any:
        return await self._request("POST", "/api/models/unload")

    async def is_available(self) -> bool:
        try:
            await self.models()
            return True
        except (SwapUnavailable, SwapResponseError):
            return False

    async def events(self) -> AsyncIterator[str]:
        try:
            async with self._client.stream(
                "GET", "/api/events", timeout=self._event_timeout
            ) as response:
                if not response.is_success:
                    body = (await response.aread()).decode(errors="replace")
                    raise SwapResponseError(response.status_code, body)
                lines: list[str] = []
                async for line in response.aiter_lines():
                    if line == "":
                        if lines:
                            yield "\n".join(lines) + "\n\n"
                            lines.clear()
                    else:
                        lines.append(line)
                if lines:
                    yield "\n".join(lines) + "\n\n"
        except SwapResponseError:
            raise
        except httpx.RequestError as error:
            raise SwapUnavailable(str(error)) from error

    async def _request(
        self, method: str, path: str, *, timeout: httpx.Timeout | None = None
    ) -> Any:
        try:
            response = await self._client.request(
                method, path, timeout=timeout or self._request_timeout
            )
        except httpx.ReadTimeout as error:
            raise SwapReadTimeout(str(error)) from error
        except httpx.RequestError as error:
            raise SwapUnavailable(str(error)) from error
        if not response.is_success:
            raise SwapResponseError(response.status_code, response.text)
        if not response.content:
            return None
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            try:
                return response.json()
            except json.JSONDecodeError:
                return response.text
        return response.text
