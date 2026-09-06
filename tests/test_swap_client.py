from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
import respx

from llama_swap_console.swap_client import (
    LlamaSwapClient,
    SwapReadTimeout,
    SwapResponseError,
    SwapUnavailable,
)


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:9292") as http_client:
        yield LlamaSwapClient(http_client)


@respx.mock
@pytest.mark.asyncio
async def test_lists_models_and_running_state(client: LlamaSwapClient) -> None:
    respx.get("http://127.0.0.1:9292/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "alpha"}]})
    )
    respx.get("http://127.0.0.1:9292/running").mock(
        return_value=httpx.Response(200, json={"alpha": {"port": 10001}})
    )

    assert await client.models() == {"data": [{"id": "alpha"}]}
    assert await client.running() == {"alpha": {"port": 10001}}


@respx.mock
@pytest.mark.asyncio
async def test_load_and_unload_quote_model_ids(client: LlamaSwapClient) -> None:
    load = respx.get("http://127.0.0.1:9292/upstream/a%2Fb%20model/").mock(
        return_value=httpx.Response(200, json={"status": "ready"})
    )
    unload = respx.post(
        "http://127.0.0.1:9292/api/models/unload/a%2Fb%20model"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))

    assert await client.load("a/b model") == {"status": "ready"}
    assert await client.unload("a/b model") == {"ok": True}
    assert load.called and unload.called
    assert load.calls.last.request.extensions["timeout"]["read"] == 10.0


@respx.mock
@pytest.mark.asyncio
async def test_load_returns_none_for_a_successful_empty_response(
    client: LlamaSwapClient,
) -> None:
    respx.get("http://127.0.0.1:9292/upstream/alpha/").mock(
        return_value=httpx.Response(200)
    )

    assert await client.load("alpha") is None


@respx.mock
@pytest.mark.asyncio
async def test_unload_all_and_health(client: LlamaSwapClient) -> None:
    respx.post("http://127.0.0.1:9292/api/models/unload").mock(
        return_value=httpx.Response(204)
    )
    respx.get("http://127.0.0.1:9292/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    assert await client.unload_all() is None
    assert await client.is_available() is True


@respx.mock
@pytest.mark.asyncio
async def test_non_success_response_includes_bounded_body(client: LlamaSwapClient) -> None:
    respx.get("http://127.0.0.1:9292/running").mock(
        return_value=httpx.Response(500, text="x" * 2000)
    )

    with pytest.raises(SwapResponseError) as caught:
        await client.running()

    assert caught.value.status == 500
    assert len(caught.value.body) == 1000


@pytest.mark.asyncio
async def test_connection_errors_are_normalized() -> None:
    async def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:9292", transport=httpx.MockTransport(fail)
    ) as http_client:
        client = LlamaSwapClient(http_client)
        with pytest.raises(SwapUnavailable, match="offline"):
            await client.models()
        assert await client.is_available() is False


@pytest.mark.asyncio
async def test_load_read_timeout_is_distinguished_from_an_unavailable_upstream() -> None:
    async def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow load", request=request)

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:9292", transport=httpx.MockTransport(fail)
    ) as http_client:
        client = LlamaSwapClient(http_client)

        with pytest.raises(SwapReadTimeout, match="slow load"):
            await client.load("alpha")


@respx.mock
@pytest.mark.asyncio
async def test_sse_frames_are_forwarded_without_reinterpretation(
    client: LlamaSwapClient,
) -> None:
    body = "event: log\ndata: first\ndata: second\n\n: heartbeat\n\nevent: state\ndata: {\\\"x\\\":1}\n"
    respx.get("http://127.0.0.1:9292/api/events").mock(
        return_value=httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    )

    frames = [frame async for frame in client.events()]

    assert frames == [
        "event: log\ndata: first\ndata: second\n\n",
        ": heartbeat\n\n",
        'event: state\ndata: {\\"x\\":1}\n\n',
    ]


@respx.mock
@pytest.mark.asyncio
async def test_sse_http_error_is_normalized(client: LlamaSwapClient) -> None:
    respx.get("http://127.0.0.1:9292/api/events").mock(
        return_value=httpx.Response(503, text="not ready")
    )

    with pytest.raises(SwapResponseError) as caught:
        async for _ in client.events():
            pass

    assert caught.value.status == 503


@respx.mock
@pytest.mark.asyncio
async def test_decode_speed_prefers_positive_llama_swap_activity(
    client: LlamaSwapClient,
) -> None:
    respx.get("http://127.0.0.1:9292/api/metrics/activity").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"model": "alpha", "tokens": {"tokens_per_second": 73.25}}]},
        )
    )

    speed = await client.decode_speed("alpha")

    assert speed == {
        "tokens_per_second": 73.25,
        "source": "llama-swap-activity",
        "scope": "request",
        "running_requests": None,
    }


@pytest.mark.asyncio
async def test_decode_speed_does_not_reuse_stale_activity_speed() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/metrics/activity":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"model": "alpha", "tokens": {"tokens_per_second": -1}},
                        {"model": "alpha", "tokens": {"tokens_per_second": 99}},
                    ]
                },
            )
        if request.url.path == "/running":
            return httpx.Response(200, json={"running": [{"model": "alpha", "state": "ready"}]})
        return httpx.Response(
            200,
            text=(
                'vllm:generation_tokens_total{model_name="alpha"} 100\n'
                'vllm:num_requests_running{model_name="alpha"} 1\n'
            ),
        )

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:9292", transport=httpx.MockTransport(respond)
    ) as http_client:
        measured = LlamaSwapClient(http_client)

        speed = await measured.decode_speed("alpha")

    assert speed["source"] == "vllm-generation-counter"


@pytest.mark.asyncio
async def test_decode_speed_uses_vllm_generation_counter_delta_when_activity_has_no_speed() -> None:
    activity = '{"data":[{"model":"alpha","tokens":{"tokens_per_second":-1}}]}'
    samples = iter(
        [
            "vllm:generation_tokens_total{model_name=\"alpha\"} 100\n"
            "vllm:num_requests_running{model_name=\"alpha\"} 1\n",
            "vllm:generation_tokens_total{model_name=\"alpha\"} 220\n"
            "vllm:num_requests_running{model_name=\"alpha\"} 2\n",
        ]
    )
    times = iter([10.0, 12.0])

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/metrics/activity":
            return httpx.Response(200, text=activity, headers={"content-type": "application/json"})
        if request.url.path == "/running":
            return httpx.Response(200, json={"running": [{"model": "alpha", "state": "ready"}]})
        return httpx.Response(200, text=next(samples))

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:9292", transport=httpx.MockTransport(respond)
    ) as http_client:
        measured = LlamaSwapClient(http_client, clock=lambda: next(times))

        assert await measured.decode_speed("alpha") == {
            "tokens_per_second": None,
            "source": "vllm-generation-counter",
            "scope": "aggregate",
            "running_requests": 1,
        }
        assert await measured.decode_speed("alpha") == {
            "tokens_per_second": 60.0,
            "source": "vllm-generation-counter",
            "scope": "aggregate",
            "running_requests": 2,
        }


@pytest.mark.asyncio
async def test_decode_speed_never_probes_upstream_for_stopped_model() -> None:
    upstream_hits: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/upstream/"):
            upstream_hits.append(request.url.path)
            return httpx.Response(200, text="vllm:generation_tokens_total 1\n")
        if request.url.path == "/running":
            return httpx.Response(200, json={"running": []})
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:9292", transport=httpx.MockTransport(respond)
    ) as http_client:
        measured = LlamaSwapClient(http_client)

        speed = await measured.decode_speed("alpha")

    assert speed["source"] == "not-running"
    assert speed["tokens_per_second"] is None
    assert upstream_hits == []
