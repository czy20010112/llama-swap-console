from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from llama_swap_console.app import create_app
from llama_swap_console.command_codec import CommandCodec
from llama_swap_console.config_store import ConfigStore
from llama_swap_console.gpu_monitor import GpuSnapshot
from llama_swap_console.model_scanner import ModelScanner
from llama_swap_console.model_service import ModelService
from llama_swap_console.settings import Settings


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

    async def models(self):
        return {
            "data": [
                {"id": model_id, "status": {"value": "unloaded"}}
                for model_id in sorted(self.model_ids)
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
