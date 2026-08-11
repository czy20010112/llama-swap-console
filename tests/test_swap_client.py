from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
import respx

from llama_swap_console.swap_client import (
    LlamaSwapClient,
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
