from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from ruamel.yaml import YAML

from llama_swap_console.app import create_app
from llama_swap_console.command_codec import CommandCodec
from llama_swap_console.config_store import ConfigStore
from llama_swap_console.gpu_monitor import GpuSnapshot
from llama_swap_console.model_scanner import ModelScanner
from llama_swap_console.model_service import ModelService
from llama_swap_console.schemas import ModelRegisterRequest, ModelUpdateRequest
from llama_swap_console.settings import Settings
from llama_swap_console.swap_client import LlamaSwapClient


CONFIG = """models:
  alpha:
    name: Alpha
    description: Existing model
    cmd: /opt/llama-server --model "{model}" --port ${{PORT}} --ctx-size 4096
    customKey: keep-me
  zeta:
    name: Able
    description: Sort before Alpha by display name
    cmd: /opt/llama-server --model "{model}" --port ${{PORT}} --ctx-size 2048
"""


class FakeSwap:
    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.unloaded: list[str] = []
        self.model_ids = {"alpha"}
        self.config_path: Path | None = None

    async def models(self):
        model_ids = self.model_ids
        if self.config_path is not None:
            document = YAML(typ="safe").load(self.config_path.read_text(encoding="utf-8"))
            model_ids = set(document.get("models", {}))
        return {
            "data": [
                {"id": model_id, "status": {"value": "unloaded"}}
                for model_id in sorted(model_ids)
            ]
        }

    async def running(self):
        return {"running": []}

    async def load(self, model_id: str):
        self.loaded.append(model_id)
        return {"ok": True}

    async def unload(self, model_id: str):
        self.unloaded.append(model_id)
        return {"ok": True}

    async def unload_all(self):
        self.unloaded.append("*")
        return None

    async def events(self):
        yield "event: log\ndata: hello\n\n"


class FakeGpu:
    async def sample(self):
        return GpuSnapshot(gpus=(), processes=(), sampled_at=1.0)


class StartingSwap(FakeSwap):
    """External llama-swap state transitions used by lifecycle API tests."""

    def __init__(self) -> None:
        super().__init__()
        self.status = "unloaded"

    async def models(self):
        return {
            "data": [
                {"id": model_id, "status": {"value": self.status}}
                for model_id in sorted(self.model_ids)
            ]
        }

    async def load(self, model_id: str):
        self.loaded.append(model_id)
        self.status = "starting"
        return {"ok": True}


class TimeoutThenStartingSwap(StartingSwap):
    async def load(self, model_id: str):
        self.loaded.append(model_id)
        self.status = "loading"
        from llama_swap_console.swap_client import SwapReadTimeout

        raise SwapReadTimeout("read timeout")


class TimeoutThenReadySwap(StartingSwap):
    async def load(self, model_id: str):
        self.loaded.append(model_id)
        self.status = "ready"
        from llama_swap_console.swap_client import SwapReadTimeout

        raise SwapReadTimeout("read timeout")


class EmptyLoadSwap(StartingSwap):
    def __init__(self, status_after_load: str) -> None:
        super().__init__()
        self.status_after_load = status_after_load

    async def load(self, model_id: str):
        self.loaded.append(model_id)
        self.status = self.status_after_load
        return None


class EmptyLoadWithUnavailableStatusSwap(EmptyLoadSwap):
    def __init__(self) -> None:
        super().__init__("unloaded")
        self.load_finished = False

    async def models(self):
        if self.load_finished:
            from llama_swap_console.swap_client import SwapUnavailable

            raise SwapUnavailable("status unavailable")
        return await super().models()

    async def load(self, model_id: str):
        result = await super().load(model_id)
        self.load_finished = True
        return result


class EmptyLoadWithRunningStatusSwap(EmptyLoadSwap):
    def __init__(self) -> None:
        super().__init__("unknown")

    async def running(self):
        return {"alpha": {"state": "starting"}}


class ConflictingLifecycleStatusSwap(EmptyLoadSwap):
    def __init__(self, running_status: str | None) -> None:
        super().__init__("loaded")
        self.running_status = running_status

    async def running(self):
        if self.running_status is None:
            return {}
        return {"alpha": {"state": self.running_status}}


class RealRunningPayloadSwap(EmptyLoadSwap):
    def __init__(self, running_status: str | None) -> None:
        super().__init__("loaded")
        self.running_status = running_status

    async def running(self):
        running = []
        if self.running_status is not None:
            running.append(
                {
                    "model": "alpha",
                    "state": self.running_status,
                    "cmd": "/opt/llama-server --model alpha.gguf",
                    "proxy": "http://localhost:10006",
                    "ttl": 0,
                    "name": "Alpha",
                    "description": "",
                }
            )
        return {"running": running}


class ReadTimeoutAfterSuccessHeaders(httpx.AsyncByteStream):
    async def __aiter__(self):
        request = httpx.Request("GET", "http://127.0.0.1:9292/upstream/alpha/")
        raise httpx.ReadTimeout("body arrived at the read deadline", request=request)
        yield b""


class ErrorLoadSwap(StartingSwap):
    async def load(self, model_id: str):
        from llama_swap_console.swap_client import SwapResponseError

        raise SwapResponseError(502, "load rejected")


class OfflineLoadSwap(StartingSwap):
    async def load(self, model_id: str):
        from llama_swap_console.swap_client import SwapUnavailable

        raise SwapUnavailable("connection refused")


class BlockingLifecycleSwap(StartingSwap):
    def __init__(self) -> None:
        super().__init__()
        self.load_started = asyncio.Event()
        self.release_load = asyncio.Event()
        self.operations: list[str] = []

    async def load(self, model_id: str):
        self.loaded.append(model_id)
        self.operations.append("load")
        self.status = "starting"
        self.load_started.set()
        await self.release_load.wait()
        self.status = "ready"
        return {"ok": True}

    async def unload(self, model_id: str):
        self.unloaded.append(model_id)
        self.operations.append("unload")
        self.status = "unloaded"
        return {"ok": True}


class BlockingLoadWithUnavailableStatusSwap(BlockingLifecycleSwap):
    async def models(self):
        if self.load_started.is_set():
            from llama_swap_console.swap_client import SwapUnavailable

            raise SwapUnavailable("status unavailable")
        return await super().models()


class BlockingUnloadSwap(BlockingLifecycleSwap):
    def __init__(self) -> None:
        super().__init__()
        self.unload_started = asyncio.Event()
        self.release_unload = asyncio.Event()

    async def unload(self, model_id: str):
        self.unloaded.append(model_id)
        self.operations.append("unload")
        self.unload_started.set()
        await self.release_unload.wait()
        self.status = "unloaded"
        return {"ok": True}


class BlockingConfigReloadSwap(FakeSwap):
    """Blocks selected config-observation calls to make transaction cancellation deterministic."""

    def __init__(self, *blocked_calls: int) -> None:
        super().__init__()
        self.blocked_calls = set(blocked_calls)
        self.models_calls = 0
        self.observation_blocked = asyncio.Event()
        self.observed_model_ids: list[set[str]] = []

    async def models(self):
        assert self.config_path is not None
        self.models_calls += 1
        document = YAML(typ="safe").load(self.config_path.read_text(encoding="utf-8"))
        model_ids = set(document.get("models", {}))
        self.observed_model_ids.append(model_ids)
        if self.models_calls in self.blocked_calls:
            self.observation_blocked.set()
            await asyncio.Event().wait()
        return {
            "data": [
                {"id": model_id, "status": {"value": "unloaded"}}
                for model_id in sorted(model_ids)
            ]
        }


class FailingThenRecoveringLoadSwap(BlockingLifecycleSwap):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_load = True

    async def load(self, model_id: str):
        self.loaded.append(model_id)
        self.operations.append("load")
        self.load_started.set()
        await self.release_load.wait()
        if self.fail_next_load:
            self.fail_next_load = False
            from llama_swap_console.swap_client import SwapUnavailable

            raise SwapUnavailable("connection dropped")
        self.status = "ready"
        return {"ok": True}


class StableExistingModelSwap(StartingSwap):
    def __init__(self) -> None:
        super().__init__()
        self.models_calls = 0

    async def models(self):
        self.models_calls += 1
        return await super().models()


class ReloadingExistingModelSwap(StableExistingModelSwap):
    async def models(self):
        self.models_calls += 1
        if self.models_calls == 1:
            return {"data": []}
        return await StartingSwap.models(self)


class TransientPrewriteStatusFailureSwap(StableExistingModelSwap):
    async def models(self):
        self.models_calls += 1
        if self.models_calls == 1:
            from llama_swap_console.swap_client import SwapUnavailable

            raise SwapUnavailable("status probe unavailable")
        if self.models_calls == 2:
            return {"data": []}
        return await StartingSwap.models(self)


class AbsentThenVisibleExistingModelSwap(StableExistingModelSwap):
    async def models(self):
        self.models_calls += 1
        if self.models_calls == 1:
            return {"data": []}
        return await StartingSwap.models(self)


class ChangesToStartingSwap(StartingSwap):
    def __init__(self) -> None:
        super().__init__()
        self.models_calls = 0

    async def models(self):
        self.models_calls += 1
        if self.models_calls > 1:
            self.status = "starting"
        return await super().models()


@pytest.fixture
def console(tmp_path: Path):
    model_root = tmp_path / "models"
    model_root.mkdir()
    alpha = model_root / "alpha.gguf"
    alpha.write_bytes(b"not-real-gguf")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(CONFIG.format(model=alpha), encoding="utf-8")
    settings = Settings(
        config_path=config_path,
        model_roots=(model_root,),
        backup_dir=tmp_path / "backups",
    )
    swap = FakeSwap()
    swap.config_path = config_path
    service = ModelService(
        store=ConfigStore(config_path, settings.backup_dir),
        codec=CommandCodec(),
        scanner=ModelScanner(settings.model_roots),
        swap=swap,
        gpu=FakeGpu(),
        allowed_roots=settings.model_roots,
    )
    with TestClient(create_app(settings, service=service)) as client:
        yield client, service, swap, model_root


def test_lists_and_reads_structured_models(console) -> None:
    client, _, _, _ = console

    listing = client.get("/api/models")
    detail = client.get("/api/models/alpha")

    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["models"]] == ["zeta", "alpha"]
    assert listing.json()["models"][1]["status"] == "unloaded"
    assert listing.json()["llama_swap_available"] is True
    assert detail.status_code == 200
    assert detail.json()["settings"]["backend"] == "llama_cpp"
    assert detail.json()["settings"]["context_length"] == 4096
    assert len(detail.json()["revision"]) == 64


def test_structured_update_preserves_unknown_yaml_fields(console) -> None:
    client, service, _, _ = console
    detail = client.get("/api/models/alpha").json()
    body = {
        "revision": detail["revision"],
        "name": "Alpha edited",
        "description": "Changed",
        "settings": detail["settings"],
        "reload": False,
    }
    body["settings"]["context_length"] = 8192

    response = client.put("/api/models/alpha", json=body)

    assert response.status_code == 200
    snapshot = service.store.read()
    assert snapshot.document["models"]["alpha"]["customKey"] == "keep-me"
    assert "--ctx-size 8192" in snapshot.document["models"]["alpha"]["cmd"]


def test_update_rejects_stale_revision_and_raw_command_fields(console) -> None:
    client, _, _, _ = console
    detail = client.get("/api/models/alpha").json()
    body = {
        "revision": "0" * 64,
        "name": "Alpha",
        "description": "x",
        "settings": detail["settings"],
        "reload": False,
    }
    assert client.put("/api/models/alpha", json=body).status_code == 409
    body["cmd"] = "rm -rf something"
    assert client.put("/api/models/alpha", json=body).status_code == 422


def test_update_rejects_launcher_or_unknown_argument_changes(console) -> None:
    client, _, _, _ = console
    detail = client.get("/api/models/alpha").json()
    body = {
        "revision": detail["revision"],
        "name": "Alpha",
        "description": "",
        "settings": detail["settings"],
        "reload": False,
    }
    body["settings"]["launch_tokens"] = ["/tmp/arbitrary-launcher"]

    response = client.put("/api/models/alpha", json=body)

    assert response.status_code == 422
    assert "read-only" in response.json()["detail"]


def test_external_origin_cannot_call_write_api(console) -> None:
    client, _, _, _ = console

    response = client.post(
        "/api/models/unload-all", headers={"Origin": "https://example.invalid"}
    )

    assert response.status_code == 403
    assert client.post(
        "/api/models/unload-all", headers={"Origin": "http://localhost:9293"}
    ).status_code == 200


def test_lifecycle_operations_are_whitelisted(console) -> None:
    client, _, swap, _ = console

    assert client.post("/api/models/alpha/load").status_code == 200
    assert client.post("/api/models/alpha/unload").status_code == 200
    assert client.post("/api/models/missing/load").status_code == 404
    assert swap.loaded == ["alpha"]
    assert swap.unloaded == ["alpha"]


def test_load_timeout_with_upstream_starting_returns_accepted(console) -> None:
    client, service, _, _ = console
    swap = TimeoutThenStartingSwap()
    service.swap = swap

    response = client.post("/api/models/alpha/load")

    assert response.status_code == 202
    assert response.json() == {"result": None, "status": "loading"}
    assert swap.loaded == ["alpha"]


def test_unload_does_not_compete_with_an_untracked_starting_load(console) -> None:
    client, service, _, _ = console
    swap = StartingSwap()
    swap.status = "starting"
    service.swap = swap

    response = client.post("/api/models/alpha/unload")

    assert response.status_code == 200
    assert response.json() == {"result": {"ok": True}}
    assert swap.unloaded == ["alpha"]


def test_load_with_an_unreachable_upstream_still_returns_service_unavailable(console) -> None:
    client, service, _, _ = console
    service.swap = OfflineLoadSwap()

    response = client.post("/api/models/alpha/load")

    assert response.status_code == 503
    assert "connection refused" in response.json()["detail"]


def test_duplicate_load_while_upstream_is_starting_does_not_call_upstream_twice(console) -> None:
    client, service, _, _ = console
    swap = StartingSwap()
    service.swap = swap

    first = client.post("/api/models/alpha/load")
    duplicate = client.post("/api/models/alpha/load")

    assert first.status_code == 200
    assert duplicate.status_code == 202
    assert duplicate.json()["status"] == "starting"
    assert swap.loaded == ["alpha"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["ready", "running", "loaded"])
async def test_load_is_idempotent_for_an_active_model(console, status: str) -> None:
    _, service, _, _ = console
    swap = StartingSwap()
    swap.status = status
    service.swap = swap

    result = await service.load("alpha")

    assert result.status == status
    assert swap.loaded == []


@pytest.mark.asyncio
async def test_starting_model_does_not_retain_a_lifecycle_lock(console) -> None:
    _, service, _, _ = console
    swap = StartingSwap()
    swap.status = "starting"
    service.swap = swap

    result = await service.load("alpha")

    assert result.status == "starting"
    assert service._lifecycle_locks == {}


@pytest.mark.asyncio
async def test_unload_of_an_externally_starting_model_sends_upstream_unload(console) -> None:
    _, service, _, _ = console
    swap = StartingSwap()
    swap.status = "starting"
    service.swap = swap

    result = await service.unload("alpha")

    assert result.result == {"ok": True}
    assert swap.unloaded == ["alpha"]


@pytest.mark.asyncio
async def test_load_read_timeout_is_success_when_model_is_ready(console) -> None:
    _, service, _, _ = console
    swap = TimeoutThenReadySwap()
    service.swap = swap

    result = await service.load("alpha")

    assert result.status == "ready"
    assert swap.loaded == ["alpha"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["starting", "loading"])
async def test_empty_load_response_returns_the_observed_starting_status(
    console, status: str
) -> None:
    client, service, _, _ = console
    swap = EmptyLoadSwap(status)
    service.swap = swap

    transport = httpx.ASGITransport(app=client.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
        response = await asyncio.wait_for(
            api.post("/api/models/alpha/load"), timeout=1
        )

    assert response.status_code == 202
    assert response.json() == {"result": None, "status": status}
    assert swap.loaded == ["alpha"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["ready", "running", "loaded"])
async def test_empty_load_response_returns_success_for_an_active_model(
    console, status: str
) -> None:
    client, service, _, _ = console
    swap = EmptyLoadSwap(status)
    service.swap = swap

    transport = httpx.ASGITransport(app=client.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
        response = await asyncio.wait_for(
            api.post("/api/models/alpha/load"), timeout=1
        )

    assert response.status_code == 200
    assert response.json() == {"result": None, "status": status}
    assert swap.loaded == ["alpha"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["unloaded", "unknown"])
async def test_empty_load_response_without_a_confirmed_state_returns_pending(
    console, status: str
) -> None:
    client, service, _, _ = console
    swap = EmptyLoadSwap(status)
    service.swap = swap

    transport = httpx.ASGITransport(app=client.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
        response = await asyncio.wait_for(
            api.post("/api/models/alpha/load"), timeout=1
        )

    assert response.status_code == 202
    assert response.json() == {"result": None, "status": "pending"}
    assert swap.loaded == ["alpha"]


@pytest.mark.asyncio
async def test_empty_load_response_with_an_unavailable_status_probe_returns_pending(
    console,
) -> None:
    client, service, _, _ = console
    swap = EmptyLoadWithUnavailableStatusSwap()
    service.swap = swap

    transport = httpx.ASGITransport(app=client.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
        response = await asyncio.wait_for(
            api.post("/api/models/alpha/load"), timeout=1
        )

    assert response.status_code == 202
    assert response.json() == {"result": None, "status": "pending"}
    assert swap.loaded == ["alpha"]


@pytest.mark.asyncio
async def test_empty_load_response_uses_running_state_when_models_is_unknown(
    console,
) -> None:
    client, service, _, _ = console
    swap = EmptyLoadWithRunningStatusSwap()
    service.swap = swap

    transport = httpx.ASGITransport(app=client.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
        response = await asyncio.wait_for(
            api.post("/api/models/alpha/load"), timeout=1
        )

    assert response.status_code == 202
    assert response.json() == {"result": None, "status": "starting"}
    assert swap.loaded == ["alpha"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["starting", "loading"])
async def test_empty_load_response_prefers_running_transition_over_models_active(
    console, status: str
) -> None:
    client, service, _, _ = console
    service.swap = ConflictingLifecycleStatusSwap(status)

    transport = httpx.ASGITransport(app=client.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
        response = await asyncio.wait_for(
            api.post("/api/models/alpha/load"), timeout=1
        )

    assert response.status_code == 202
    assert response.json() == {"result": None, "status": status}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["ready", "running"])
async def test_empty_load_response_accepts_explicit_running_active_state(
    console, status: str
) -> None:
    client, service, _, _ = console
    service.swap = ConflictingLifecycleStatusSwap(status)

    transport = httpx.ASGITransport(app=client.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
        response = await asyncio.wait_for(
            api.post("/api/models/alpha/load"), timeout=1
        )

    assert response.status_code == 200
    assert response.json() == {"result": None, "status": status}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("running_status", "expected"),
    [("starting", "starting"), ("loading", "loading"), (None, "loaded")],
)
async def test_model_list_prefers_running_lifecycle_status_and_falls_back_to_models(
    console, running_status: str | None, expected: str
) -> None:
    _, service, _, _ = console
    swap = ConflictingLifecycleStatusSwap(running_status)
    swap.status = "loaded"
    service.swap = swap

    result = await asyncio.wait_for(service.list_models(), timeout=1)

    alpha = next(item for item in result["models"] if item["id"] == "alpha")
    assert alpha["status"] == expected


@pytest.mark.asyncio
async def test_empty_load_response_reads_real_running_list_payload(console) -> None:
    client, service, _, _ = console
    service.swap = RealRunningPayloadSwap("starting")

    transport = httpx.ASGITransport(app=client.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
        response = await asyncio.wait_for(
            api.post("/api/models/alpha/load"), timeout=1
        )

    assert response.status_code == 202
    assert response.json() == {"result": None, "status": "starting"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("running_status", "expected"), [("starting", "starting"), (None, "loaded")]
)
async def test_model_list_reads_real_running_list_payload_and_empty_fallback(
    console, running_status: str | None, expected: str
) -> None:
    _, service, _, _ = console
    swap = RealRunningPayloadSwap(running_status)
    swap.status = "loaded"
    service.swap = swap

    result = await asyncio.wait_for(service.list_models(), timeout=1)

    alpha = next(item for item in result["models"] if item["id"] == "alpha")
    assert alpha["status"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout_after_headers", [False, True])
async def test_real_swap_client_empty_load_confirms_running_state_through_api(
    console, timeout_after_headers: bool
) -> None:
    client, service, _, _ = console
    requests: list[str] = []
    models_calls = 0

    async def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal models_calls
        requests.append(request.url.path)
        if request.url.path == "/v1/models":
            models_calls += 1
            status = "unloaded" if models_calls <= 2 else "loaded"
            return httpx.Response(
                200,
                json={"data": [{"id": "alpha", "status": {"value": status}}]},
            )
        if request.url.path == "/running":
            return httpx.Response(
                200,
                json={
                    "running": [
                        {
                            "model": "alpha",
                            "state": "starting",
                            "cmd": "/opt/llama-server --model alpha.gguf",
                            "proxy": "http://localhost:10006",
                            "ttl": 0,
                            "name": "Alpha",
                            "description": "",
                        }
                    ]
                },
            )
        if request.url.path == "/upstream/alpha/":
            if timeout_after_headers:
                return httpx.Response(200, stream=ReadTimeoutAfterSuccessHeaders())
            return httpx.Response(200, content=b"")
        raise AssertionError(f"Unexpected upstream request: {request.url}")

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:9292", transport=httpx.MockTransport(upstream)
    ) as upstream_client:
        service.swap = LlamaSwapClient(upstream_client)
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as api:
            response = await asyncio.wait_for(
                api.post("/api/models/alpha/load"), timeout=1
            )

    assert response.status_code == 202
    assert response.json() == {"result": None, "status": "starting"}
    assert "/upstream/alpha/" in requests
    assert "/running" in requests


@pytest.mark.asyncio
async def test_load_upstream_http_error_is_not_converted_to_pending(console) -> None:
    client, service, _, _ = console
    service.swap = ErrorLoadSwap()

    transport = httpx.ASGITransport(app=client.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
        response = await asyncio.wait_for(
            api.post("/api/models/alpha/load"), timeout=1
        )

    assert response.status_code == 502
    assert "load rejected" in response.json()["detail"]


@pytest.mark.asyncio
async def test_model_that_starts_while_acquiring_the_lock_does_not_retain_it(console) -> None:
    _, service, _, _ = console
    swap = ChangesToStartingSwap()
    service.swap = swap

    result = await service.load("alpha")

    assert result.status == "starting"
    assert service._lifecycle_locks == {}


@pytest.mark.asyncio
async def test_concurrent_load_requests_share_one_upstream_call(console) -> None:
    client, service, _, _ = console
    swap = BlockingLifecycleSwap()
    service.swap = swap

    transport = httpx.ASGITransport(app=client.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
        first = asyncio.create_task(api.post("/api/models/alpha/load"))
        await asyncio.wait_for(swap.load_started.wait(), timeout=1)
        second = asyncio.create_task(api.post("/api/models/alpha/load"))
        await asyncio.sleep(0)

        assert swap.loaded == ["alpha"]
        swap.release_load.set()
        first_response, second_response = await asyncio.gather(first, second)

    assert first_response.status_code == 200
    assert second_response.status_code == 202
    assert second_response.json()["status"] == "starting"
    assert swap.loaded == ["alpha"]


@pytest.mark.asyncio
async def test_duplicate_load_reuses_the_local_task_when_status_refresh_fails(console) -> None:
    _, service, _, _ = console
    swap = BlockingLoadWithUnavailableStatusSwap()
    service.swap = swap

    first = asyncio.create_task(service.load("alpha"))
    await asyncio.wait_for(swap.load_started.wait(), timeout=1)
    duplicate = await service.load("alpha")

    assert duplicate.status == "starting"
    assert swap.loaded == ["alpha"]
    swap.release_load.set()
    await first


@pytest.mark.asyncio
async def test_duplicate_load_does_not_release_the_inflight_model_lock(console) -> None:
    _, service, _, _ = console
    swap = BlockingLifecycleSwap()
    service.swap = swap

    first = asyncio.create_task(service.load("alpha"))
    await asyncio.wait_for(swap.load_started.wait(), timeout=1)
    duplicate = await service.load("alpha")

    assert duplicate.status == "starting"
    assert "alpha" in service._lifecycle_locks
    swap.release_load.set()
    await first


@pytest.mark.asyncio
async def test_unload_waits_for_an_inflight_load_of_the_same_model(console) -> None:
    _, service, _, _ = console
    swap = BlockingLifecycleSwap()
    service.swap = swap

    load = asyncio.create_task(service.load("alpha"))
    await asyncio.wait_for(swap.load_started.wait(), timeout=1)
    unload = asyncio.create_task(service.unload("alpha"))
    await asyncio.sleep(0)

    assert swap.operations == ["load"]
    swap.release_load.set()
    await asyncio.gather(load, unload)
    assert swap.operations == ["load", "unload"]


@pytest.mark.asyncio
async def test_cancelling_an_unload_waiter_does_not_cancel_the_shared_load(console) -> None:
    _, service, _, _ = console
    swap = BlockingLifecycleSwap()
    service.swap = swap

    load = asyncio.create_task(service.load("alpha"))
    await asyncio.wait_for(swap.load_started.wait(), timeout=1)
    unload = asyncio.create_task(service.unload("alpha"))
    await asyncio.sleep(0)
    unload.cancel()
    with pytest.raises(asyncio.CancelledError):
        await unload

    shared = service._lifecycle_tasks["alpha"]
    assert not shared.cancelled()
    swap.release_load.set()
    await load


@pytest.mark.asyncio
async def test_cancelling_the_initiating_unload_waiter_keeps_the_shared_unload_and_serializes_a_load(console) -> None:
    _, service, _, _ = console
    swap = BlockingUnloadSwap()
    swap.status = "ready"
    service.swap = swap

    unload = asyncio.create_task(service.unload("alpha"))
    await asyncio.wait_for(swap.unload_started.wait(), timeout=1)
    unload.cancel()
    with pytest.raises(asyncio.CancelledError):
        await unload

    shared = service._lifecycle_tasks["alpha"]
    assert not shared.cancelled()
    load = asyncio.create_task(service.load("alpha"))
    await asyncio.sleep(0)
    assert swap.operations == ["unload"]
    assert "alpha" in service._lifecycle_locks

    swap.release_unload.set()
    await asyncio.wait_for(swap.load_started.wait(), timeout=1)
    swap.release_load.set()
    await load
    assert swap.operations == ["unload", "load"]
    assert swap.loaded == ["alpha"]


@pytest.mark.asyncio
async def test_unload_all_routes_configured_models_through_the_lifecycle_coordinator(console) -> None:
    _, service, _, _ = console
    swap = BlockingLifecycleSwap()
    service.swap = swap

    load = asyncio.create_task(service.load("alpha"))
    await asyncio.wait_for(swap.load_started.wait(), timeout=1)
    unload_all = asyncio.create_task(service.unload_all())
    for _ in range(20):
        if "zeta" in swap.unloaded:
            break
        await asyncio.sleep(0)

    assert "*" not in swap.unloaded
    assert "alpha" not in swap.unloaded
    assert "zeta" in swap.unloaded
    swap.release_load.set()
    await asyncio.gather(load, unload_all)

    assert sorted(swap.unloaded) == ["alpha", "zeta"]
    assert swap.operations == ["load", "unload", "unload"]


@pytest.mark.asyncio
async def test_load_cannot_cross_an_inflight_unload_all_barrier(console) -> None:
    _, service, _, _ = console
    swap = BlockingUnloadSwap()
    swap.status = "ready"
    service.swap = swap

    unload_all = asyncio.create_task(service.unload_all())
    await asyncio.wait_for(swap.unload_started.wait(), timeout=1)
    load = asyncio.create_task(service.load("alpha"))
    await asyncio.sleep(0)

    assert swap.loaded == []
    swap.release_unload.set()
    await asyncio.wait_for(unload_all, timeout=1)
    assert swap.loaded == []

    await asyncio.wait_for(swap.load_started.wait(), timeout=1)
    swap.release_load.set()
    await asyncio.wait_for(load, timeout=1)
    assert swap.loaded == ["alpha"]


@pytest.mark.asyncio
async def test_overlapping_unload_all_calls_share_one_barrier_until_the_last_call_finishes(
    console,
) -> None:
    _, service, _, _ = console
    swap = BlockingUnloadSwap()
    swap.status = "ready"
    service.swap = swap

    first = asyncio.create_task(service.unload_all())
    await asyncio.wait_for(swap.unload_started.wait(), timeout=1)
    second = asyncio.create_task(service.unload_all())
    load = asyncio.create_task(service.load("alpha"))
    await asyncio.sleep(0)

    assert swap.loaded == []
    swap.status = "unloaded"
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    await asyncio.sleep(0)
    assert swap.loaded == []

    swap.release_unload.set()
    await asyncio.wait_for(second, timeout=1)
    await asyncio.wait_for(swap.load_started.wait(), timeout=1)
    swap.release_load.set()
    await asyncio.wait_for(load, timeout=1)

    assert swap.loaded == ["alpha"]


@pytest.mark.asyncio
async def test_inflight_load_keeps_its_model_lock_until_the_task_finishes(console) -> None:
    _, service, _, _ = console
    swap = BlockingLifecycleSwap()
    service.swap = swap

    load = asyncio.create_task(service.load("alpha"))
    await asyncio.wait_for(swap.load_started.wait(), timeout=1)

    assert "alpha" in service._lifecycle_locks
    swap.release_load.set()
    await load
    assert service._lifecycle_locks == {}


@pytest.mark.asyncio
async def test_cancelling_one_waiter_does_not_cancel_the_shared_load(console) -> None:
    _, service, _, _ = console
    swap = BlockingLifecycleSwap()
    service.swap = swap

    first = asyncio.create_task(service.load("alpha"))
    await asyncio.wait_for(swap.load_started.wait(), timeout=1)
    second = asyncio.create_task(service.load("alpha"))
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    shared = service._lifecycle_tasks["alpha"]
    assert not shared.cancelled()
    swap.release_load.set()
    assert (await second).status == "starting"
    await shared
    assert service._lifecycle_tasks == {}
    assert service._lifecycle_locks == {}


@pytest.mark.asyncio
async def test_cancelled_load_waiter_consumes_the_background_failure_and_allows_a_retry(console) -> None:
    _, service, _, _ = console
    swap = FailingThenRecoveringLoadSwap()
    service.swap = swap
    loop = asyncio.get_running_loop()
    reported: list[dict[str, object]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: reported.append(context))
    try:
        first = asyncio.create_task(service.load("alpha"))
        await asyncio.wait_for(swap.load_started.wait(), timeout=1)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first

        swap.release_load.set()
        for _ in range(20):
            if not service._lifecycle_tasks:
                break
            await asyncio.sleep(0)

        assert service._lifecycle_tasks == {}
        assert service._lifecycle_locks == {}
        assert not any(
            "Task exception was never retrieved" in str(context.get("message"))
            for context in reported
        )

        assert (await service.load("alpha")).result == {"ok": True}
        assert swap.loaded == ["alpha", "alpha"]
    finally:
        loop.set_exception_handler(previous_handler)


def test_existing_model_hot_reload_rejects_a_constant_model_id_and_restores_the_configuration(console) -> None:
    client, service, _, _ = console
    swap = StableExistingModelSwap()
    service.swap = swap
    service.poll_interval = 0
    service.reload_timeout = 0
    detail = client.get("/api/models/alpha").json()

    response = client.put(
        "/api/models/alpha",
        json={
            "revision": detail["revision"],
            "name": "Updated Alpha",
            "description": detail["description"],
            "settings": detail["settings"],
            "reload": False,
        },
    )

    assert response.status_code == 502
    assert service.store.read().document["models"]["alpha"]["name"] == "Alpha"


@pytest.mark.asyncio
async def test_existing_model_hot_reload_waits_for_a_missing_id_to_reappear(console) -> None:
    _, service, _, _ = console
    swap = ReloadingExistingModelSwap()
    service.swap = swap
    service.poll_interval = 0

    await service._confirm_hot_reload("alpha", expected_present=False)
    await service._confirm_hot_reload("alpha", expected_present=True)

    assert swap.models_calls >= 2


def _update_request(service: ModelService) -> ModelUpdateRequest:
    detail = service._detail(service.store.read(), "alpha")
    return ModelUpdateRequest(
        revision=detail["revision"],
        name="Updated Alpha",
        description="Changed",
        settings=detail["settings"],
        reload=False,
    )


def _register_request(
    *, model_id: str, model_path: Path, revision: str
) -> ModelRegisterRequest:
    return ModelRegisterRequest(
        revision=revision,
        model_id=model_id,
        name="Beta",
        description="New model",
        settings={
            "backend": "llama_cpp",
            "launch_tokens": ["/opt/llama-server"],
            "model_path": str(model_path),
            "context_length": 4096,
            "port_token": "${PORT}",
            "llama_cpp": {},
            "vllm": None,
            "unknown_tokens": [],
        },
    )


@pytest.mark.asyncio
async def test_cancelling_register_after_config_write_restores_config_confirms_absence_and_cleans_backup(
    console,
) -> None:
    _, service, _, model_root = console
    beta = model_root / "beta.gguf"
    beta.write_bytes(b"candidate")
    await service.scan()
    candidate_id = next(
        candidate_id
        for candidate_id, candidate in service._discovered.items()
        if Path(candidate.path) == beta
    )
    original = service.store.read().raw
    swap = BlockingConfigReloadSwap(1)
    swap.config_path = service.store.config_path
    service.swap = swap

    task = asyncio.create_task(
        service.register(
            candidate_id,
            _register_request(model_id="beta", model_path=beta, revision=service.store.read().revision),
        )
    )
    await asyncio.wait_for(swap.observation_blocked.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert service.store.read().raw == original
    assert "beta" not in service.store.read().document["models"]
    assert swap.observed_model_ids[-1] == {"alpha", "zeta"}
    assert not list(service.store.backup_dir.glob("*-config.yaml"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("blocked_call", "expected_absent"), [(1, True), (2, False)]
)
async def test_cancelling_existing_model_reload_transaction_restores_config_confirms_presence_and_cleans_backups(
    console, blocked_call: int, expected_absent: bool
) -> None:
    _, service, _, _ = console
    original = service.store.read().raw
    swap = BlockingConfigReloadSwap(blocked_call)
    swap.config_path = service.store.config_path
    service.swap = swap

    task = asyncio.create_task(service.update_model("alpha", _update_request(service)))
    await asyncio.wait_for(swap.observation_blocked.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert service.store.read().raw == original
    assert "alpha" in service.store.read().document["models"]
    assert ("alpha" not in swap.observed_model_ids[blocked_call - 1]) is expected_absent
    assert swap.observed_model_ids[-1] == {"alpha", "zeta"}
    assert not list(service.store.backup_dir.glob("*-config.yaml"))


def test_reload_of_an_existing_model_waits_for_a_hot_reload_barrier(console) -> None:
    client, service, _, _ = console
    swap = ReloadingExistingModelSwap()
    service.swap = swap
    service.poll_interval = 0.01
    detail = client.get("/api/models/alpha").json()

    response = client.put(
        "/api/models/alpha",
        json={
            "revision": detail["revision"],
            "name": detail["name"],
            "description": detail["description"],
            "settings": detail["settings"],
            "reload": True,
        },
    )

    assert response.status_code == 200
    assert swap.models_calls >= 3
    assert swap.unloaded == ["alpha"]
    assert swap.loaded == ["alpha"]


def test_reload_preserves_a_config_update_when_the_prewrite_status_probe_is_transiently_down(console) -> None:
    client, service, _, _ = console
    swap = TransientPrewriteStatusFailureSwap()
    service.swap = swap
    service.poll_interval = 0
    service.hot_reload_settle_time = 0
    detail = client.get("/api/models/alpha").json()

    response = client.put(
        "/api/models/alpha",
        json={
            "revision": detail["revision"],
            "name": "Updated Alpha",
            "description": detail["description"],
            "settings": detail["settings"],
            "reload": False,
        },
    )

    assert response.status_code == 200
    assert service.store.read().document["models"]["alpha"]["name"] == "Updated Alpha"


def test_existing_model_missing_from_the_prewrite_snapshot_uses_the_reload_barrier(console) -> None:
    client, service, _, _ = console
    swap = AbsentThenVisibleExistingModelSwap()
    service.swap = swap
    service.poll_interval = 0
    service.hot_reload_settle_time = 0.05
    detail = client.get("/api/models/alpha").json()

    started = time.monotonic()
    response = client.put(
        "/api/models/alpha",
        json={
            "revision": detail["revision"],
            "name": "Updated Alpha",
            "description": detail["description"],
            "settings": detail["settings"],
            "reload": False,
        },
    )

    assert response.status_code == 200
    assert swap.models_calls >= 2


def test_scan_and_register_candidate(console) -> None:
    client, _, swap, model_root = console
    beta = model_root / "beta.gguf"
    beta.write_bytes(b"broken metadata is still discoverable")

    scan = client.post("/api/scan")
    discovered = client.get("/api/discovered-models").json()["models"]
    beta_candidate = next(item for item in discovered if item["path"].endswith("beta.gguf"))
    swap.model_ids.add("beta")
    register = client.post(
        f"/api/discovered-models/{beta_candidate['candidate_id']}/register",
        json={
            "revision": scan.json()["revision"],
            "model_id": "beta",
            "name": "Beta",
            "description": "New model",
            "settings": {
                "backend": "llama_cpp",
                "launch_tokens": ["/opt/llama-server"],
                "model_path": str(beta),
                "context_length": 4096,
                "port_token": "${PORT}",
                "llama_cpp": {},
                "vllm": None,
                "unknown_tokens": [],
            },
        },
    )

    assert scan.status_code == 200
    assert register.status_code == 200
    assert client.get("/api/models/beta").status_code == 200


def test_registration_rejects_path_outside_allowed_root(console, tmp_path: Path) -> None:
    client, _, _, model_root = console
    candidate = model_root / "candidate.gguf"
    candidate.write_bytes(b"candidate")
    scan = client.post("/api/scan").json()
    discovered = client.get("/api/discovered-models").json()["models"]
    item = next(row for row in discovered if row["path"].endswith("candidate.gguf"))
    outside = tmp_path / "outside.gguf"
    outside.write_bytes(b"outside")

    response = client.post(
        f"/api/discovered-models/{item['candidate_id']}/register",
        json={
            "revision": scan["revision"],
            "model_id": "outside",
            "name": "Outside",
            "description": "",
            "settings": {
                "backend": "llama_cpp",
                "launch_tokens": ["/opt/llama-server"],
                "model_path": str(outside),
                "context_length": 4096,
                "llama_cpp": {},
            },
        },
    )

    assert response.status_code == 422


def test_registration_rejects_untrusted_launcher(console) -> None:
    client, _, _, model_root = console
    candidate = model_root / "untrusted.gguf"
    candidate.write_bytes(b"candidate")
    scan = client.post("/api/scan").json()
    discovered = client.get("/api/discovered-models").json()["models"]
    item = next(row for row in discovered if row["path"].endswith("untrusted.gguf"))

    response = client.post(
        f"/api/discovered-models/{item['candidate_id']}/register",
        json={
            "revision": scan["revision"],
            "model_id": "untrusted",
            "name": "Untrusted",
            "description": "",
            "settings": {
                "backend": "llama_cpp",
                "launch_tokens": ["/tmp/arbitrary-launcher"],
                "model_path": str(candidate),
                "context_length": 4096,
                "llama_cpp": {},
            },
        },
    )

    assert response.status_code == 422
    assert "trusted launcher" in response.json()["detail"]


def test_failed_hot_reload_restores_configuration(console) -> None:
    client, service, _, model_root = console
    candidate = model_root / "rejected.gguf"
    candidate.write_bytes(b"candidate")
    scan = client.post("/api/scan").json()
    discovered = client.get("/api/discovered-models").json()["models"]
    item = next(row for row in discovered if row["path"].endswith("rejected.gguf"))
    service.swap = FakeSwap()
    service.reload_timeout = 0

    response = client.post(
        f"/api/discovered-models/{item['candidate_id']}/register",
        json={
            "revision": scan["revision"],
            "model_id": "rejected",
            "name": "Rejected",
            "description": "",
            "settings": {
                "backend": "llama_cpp",
                "launch_tokens": ["/opt/llama-server"],
                "model_path": str(candidate),
                "context_length": 4096,
                "llama_cpp": {},
            },
        },
    )

    assert response.status_code == 502
    assert client.get("/api/models/rejected").status_code == 404


def test_gpu_events_and_rollback_endpoints(console) -> None:
    client, _, _, _ = console
    detail = client.get("/api/models/alpha").json()
    body = {
        "revision": detail["revision"],
        "name": "Changed",
        "description": "",
        "settings": detail["settings"],
        "reload": False,
    }
    assert client.put("/api/models/alpha", json=body).status_code == 200

    assert client.get("/api/gpu").status_code == 200
    assert "data: hello" in client.get("/api/events").text
    assert client.post("/api/config/rollback-latest").status_code == 200
    assert client.get("/api/models/alpha").json()["name"] == "Alpha"
