from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any, NamedTuple
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


class SwapUnauthorized(SwapResponseError):
    """llama-swap rejected the credential (missing, wrong or expired API key)."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(status, body)
        self.args = (
            "llama-swap rejected the credential; check LLAMA_SWAP_CONSOLE_LLAMA_SWAP_API_KEY",
        )


_AUTH_REJECTED = {401, 403}


class _MetricReading(NamedTuple):
    """One scrape of a backend's Prometheus text, reduced to what we display."""

    total: float           # cumulative generation tokens; counters are summed
    running: float         # live request count; parallel ranks repeat the same value
    throughput: float | None  # direct token/s gauge, when the backend exposes one
    source: str


class LlamaSwapClient:
    def __init__(self, client: httpx.AsyncClient, *, clock=time.monotonic) -> None:
        self._client = client
        self._clock = clock
        self._decode_samples: dict[str, tuple[float, float]] = {}
        self._request_timeout = httpx.Timeout(3.0)
        self._event_timeout = httpx.Timeout(
            connect=3.0, read=None, write=3.0, pool=3.0
        )

    async def models(self) -> Any:
        return await self._request("GET", "/v1/models")

    async def running(self) -> Any:
        return await self._request("GET", "/running")

    async def decode_speed(self, model_id: str) -> dict[str, Any]:
        activity = await self._request("GET", "/api/metrics/activity")
        latest = next(
            (item for item in activity.get("data", []) if item.get("model") == model_id),
            None,
        )
        if latest is not None:
            value = latest.get("tokens", {}).get("tokens_per_second")
            if isinstance(value, (int, float)) and value > 0:
                return {"tokens_per_second": float(value), "source": "llama-swap-activity", "scope": "request", "running_requests": None}
        # Never probe /upstream/* for a stopped model: that path proxies through
        # llama-swap, which starts the model on demand — a 2s stats poll would
        # keep waking models the user unloaded. Ask /running (live truth) first.
        try:
            live = await self.running()
            names = {item.get("model") for item in live.get("running", [])}
            if model_id not in names:
                return {"tokens_per_second": None, "source": "not-running", "scope": "aggregate", "running_requests": 0}
        except (SwapUnavailable, SwapResponseError):
            return {"tokens_per_second": None, "source": "swap-unreachable", "scope": "aggregate", "running_requests": None}
        encoded = quote(model_id, safe="")
        metrics = await self._request("GET", f"/upstream/{encoded}/metrics")
        reading = self._decode_metrics(metrics, model_id)
        now = self._clock()
        previous = self._decode_samples.get(model_id)
        self._decode_samples[model_id] = (now, reading.total)
        running = int(reading.running)

        # A live throughput gauge needs no sampling window, so the first poll after a
        # page load is already correct. This is the path sglang takes.
        if reading.throughput is not None:
            decoding = reading.throughput > 0
            return {
                "tokens_per_second": reading.throughput if decoding else None,
                "source": f"{reading.source}-throughput" if decoding else "idle",
                "scope": "model",
                "running_requests": running,
            }

        # Counter-only backends (vLLM) need two scrapes. With nothing in flight the
        # counter cannot move, and reporting that as a hard 0.0 is indistinguishable
        # from a stuck reading — say "idle" instead of inventing a measurement.
        if running <= 0:
            return {
                "tokens_per_second": None,
                "source": "idle",
                "scope": "model",
                "running_requests": 0,
            }

        speed = None
        if previous is not None and now > previous[0] and reading.total > previous[1]:
            speed = (reading.total - previous[1]) / (now - previous[0])
        return {"tokens_per_second": speed, "source": reading.source, "scope": "aggregate", "running_requests": running}

    @classmethod
    def _decode_metrics(cls, metrics: str, model_id: str) -> _MetricReading:
        for counter, running, gauge, source in (
            (
                "vllm:generation_tokens_total",
                "vllm:num_requests_running",
                None,
                "vllm-generation-counter",
            ),
            (
                "sglang:generation_tokens_total",
                "sglang:num_running_reqs",
                "sglang:gen_throughput",
                "sglang-generation-counter",
            ),
        ):
            total = cls._metric_sum(metrics, counter, model_id)
            live = cls._metric_max(metrics, running, model_id)
            if total is None or live is None:
                continue
            return _MetricReading(
                total=total,
                running=live,
                throughput=None if gauge is None else cls._metric_max(metrics, gauge, model_id),
                source=source,
            )
        raise SwapUnavailable(f"No supported generation metrics are available for {model_id!r}")

    @classmethod
    def _metric_sum(cls, metrics: str, name: str, model_id: str) -> float | None:
        """Sum a counter, which backends may split across label variants.

        sglang emits one `generation_tokens_total` series per `is_streaming` value;
        reading only the first line pins us to the non-streaming series, which never
        moves while the user chats through /v1/chat/completions.
        """

        values = cls._metric_values(metrics, name, model_id)
        return sum(values) if values else None

    @classmethod
    def _metric_max(cls, metrics: str, name: str, model_id: str) -> float | None:
        """Take the max of a gauge: every rank repeats the same value, so summing lies."""

        values = cls._metric_values(metrics, name, model_id)
        return max(values) if values else None

    @staticmethod
    def _metric_values(metrics: str, name: str, model_id: str) -> list[float]:
        pattern = re.compile(
            rf'^{re.escape(name)}\{{[^}}]*model_name="{re.escape(model_id)}"[^}}]*\}}'
            r"[ \t]+([-+0-9.eE]+)\r?$",
            re.MULTILINE,
        )
        return [float(value) for value in pattern.findall(metrics)]

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
                    raise (
                        SwapUnauthorized(response.status_code, body)
                        if response.status_code in _AUTH_REJECTED
                        else SwapResponseError(response.status_code, body)
                    )
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
            if response.status_code in _AUTH_REJECTED:
                raise SwapUnauthorized(response.status_code, response.text)
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
