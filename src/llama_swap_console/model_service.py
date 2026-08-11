from __future__ import annotations

import copy
import asyncio
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Protocol

from ruamel.yaml.comments import CommentedMap

from llama_swap_console.command_codec import CommandCodec, CommandDecodeError
from llama_swap_console.config_store import ConfigSnapshot, ConfigStore
from llama_swap_console.model_scanner import DiscoveredModel, ModelScanner
from llama_swap_console.schemas import ModelRegisterRequest, ModelUpdateRequest
from llama_swap_console.swap_client import SwapResponseError, SwapUnavailable


class ServiceNotFound(Exception):
    pass


class ServiceValidationError(Exception):
    pass


class ServiceHotReloadError(Exception):
    pass


class SwapProtocol(Protocol):
    async def models(self) -> Any: ...
    async def running(self) -> Any: ...
    async def load(self, model_id: str) -> Any: ...
    async def unload(self, model_id: str) -> Any: ...
    async def unload_all(self) -> Any: ...
    def events(self) -> Any: ...


class GpuProtocol(Protocol):
    async def sample(self) -> Any: ...


class ModelService:
    def __init__(
        self,
        *,
        store: ConfigStore,
        codec: CommandCodec,
        scanner: ModelScanner,
        swap: SwapProtocol,
        gpu: GpuProtocol,
        allowed_roots: tuple[Path, ...],
        scan_ttl: float = 300,
        reload_timeout: float = 5,
        poll_interval: float = 0.1,
    ) -> None:
        self.store = store
        self.codec = codec
        self.scanner = scanner
        self.swap = swap
        self.gpu = gpu
        self.allowed_roots = tuple(root.resolve(strict=False) for root in allowed_roots)
        self.scan_ttl = scan_ttl
        self.reload_timeout = reload_timeout
        self.poll_interval = poll_interval
        self._discovered: dict[str, DiscoveredModel] = {}
        self._scan_time = 0.0

    async def list_models(self) -> dict[str, Any]:
        snapshot = self.store.read()
        models = [
            self._detail(snapshot, model_id)
            for model_id in self._models(snapshot)
        ]
        models.sort(key=lambda item: (item["name"].casefold(), item["id"].casefold()))
        try:
            upstream = await self.swap.models()
            statuses = {
                str(item.get("id")): item.get("status", {}).get("value", "unknown")
                for item in upstream.get("data", [])
                if isinstance(item, dict) and item.get("id")
            }
            for item in models:
                item["status"] = statuses.get(item["id"], "unknown")
            available = True
        except (SwapUnavailable, SwapResponseError):
            for item in models:
                item["status"] = "unavailable"
            available = False
        return {"models": models, "revision": snapshot.revision, "llama_swap_available": available}

    async def get_model(self, model_id: str) -> dict[str, Any]:
        snapshot = self.store.read()
        self._require_model(snapshot, model_id)
        return self._detail(snapshot, model_id)

    async def update_model(
        self, model_id: str, request: ModelUpdateRequest
    ) -> dict[str, Any]:
        snapshot = self.store.read()
        existing = self._require_model(snapshot, model_id)
        self._ensure_immutable_command_fields(existing, request.settings)
        self._ensure_allowed_path(Path(request.settings.model_path))
        entry = copy.deepcopy(existing)
        entry["name"] = request.name
        entry["description"] = request.description
        entry["cmd"] = self.codec.encode(request.settings)
        capabilities = entry.get("capabilities")
        if not isinstance(capabilities, CommentedMap):
            capabilities = CommentedMap()
            entry["capabilities"] = capabilities
        capabilities["context"] = request.settings.context_length
        updated = self.store.update_model(model_id, entry, request.revision)
        await self._confirm_hot_reload(model_id)
        if request.reload:
            await self.swap.unload(model_id)
            await self.swap.load(model_id)
        return self._detail(updated, model_id)

    async def scan(self) -> dict[str, Any]:
        snapshot = self.store.read()
        registered = self._registered_paths(snapshot)
        candidates = await asyncio.to_thread(
            self.scanner.scan, registered_paths=registered
        )
        self._discovered = {item.candidate_id: item for item in candidates}
        self._scan_time = time.monotonic()
        return {
            "models": [asdict(item) for item in candidates],
            "revision": snapshot.revision,
        }

    async def discovered(self) -> dict[str, Any]:
        if time.monotonic() - self._scan_time > self.scan_ttl:
            await self.scan()
        return {"models": [asdict(item) for item in self._discovered.values()]}

    async def register(
        self, candidate_id: str, request: ModelRegisterRequest
    ) -> dict[str, Any]:
        candidate = self._discovered.get(candidate_id)
        if candidate is None:
            raise ServiceNotFound("Discovered model is unknown or expired")
        if not candidate.complete:
            raise ServiceValidationError(candidate.reason or "Model download is incomplete")
        if request.settings.backend != candidate.backend:
            raise ServiceValidationError("Backend does not match the discovered candidate")
        requested_path = Path(request.settings.model_path).resolve(strict=False)
        if requested_path != Path(candidate.path).resolve(strict=False):
            raise ServiceValidationError("Model path does not match the discovered candidate")
        self._ensure_allowed_path(requested_path)
        self._ensure_trusted_registration_template(self.store.read(), request.settings)
        entry = CommentedMap(
            {
                "name": request.name,
                "description": request.description,
                "unlisted": False,
                "cmd": self.codec.encode(request.settings),
                "capabilities": CommentedMap(
                    {"in": ["text"], "out": ["text"], "context": request.settings.context_length}
                ),
            }
        )
        updated = self.store.register_model(request.model_id, entry, request.revision)
        await self._confirm_hot_reload(request.model_id)
        self._discovered.pop(candidate_id, None)
        return self._detail(updated, request.model_id)

    async def load(self, model_id: str) -> Any:
        self._require_model(self.store.read(), model_id)
        return await self.swap.load(model_id)

    async def unload(self, model_id: str) -> Any:
        self._require_model(self.store.read(), model_id)
        return await self.swap.unload(model_id)

    async def unload_all(self) -> Any:
        return await self.swap.unload_all()

    async def gpu_snapshot(self) -> dict[str, Any]:
        return asdict(await self.gpu.sample())

    async def rollback_latest(self) -> dict[str, Any]:
        restored = self.store.rollback_latest()
        return {"revision": restored.revision, "restored": True}

    def _detail(self, snapshot: ConfigSnapshot, model_id: str) -> dict[str, Any]:
        entry = self._require_model(snapshot, model_id)
        command = entry.get("cmd")
        settings: dict[str, Any] | None = None
        compatibility_error: str | None = None
        if not isinstance(command, str):
            compatibility_error = "Model command is missing"
        else:
            try:
                settings = self.codec.decode(command).model_dump(mode="json")
            except CommandDecodeError as error:
                compatibility_error = str(error)
        return {
            "id": model_id,
            "name": str(entry.get("name") or model_id),
            "description": str(entry.get("description") or ""),
            "settings": settings,
            "compatibility_error": compatibility_error,
            "revision": snapshot.revision,
        }

    @staticmethod
    def _models(snapshot: ConfigSnapshot) -> CommentedMap:
        models = snapshot.document.get("models")
        if not isinstance(models, CommentedMap):
            raise ServiceValidationError("Configuration models node must be a mapping")
        return models

    def _require_model(self, snapshot: ConfigSnapshot, model_id: str) -> CommentedMap:
        entry = self._models(snapshot).get(model_id)
        if not isinstance(entry, CommentedMap):
            raise ServiceNotFound(f"Model {model_id!r} is not configured")
        return entry

    def _registered_paths(self, snapshot: ConfigSnapshot) -> set[Path]:
        paths: set[Path] = set()
        for entry in self._models(snapshot).values():
            if not isinstance(entry, CommentedMap) or not isinstance(entry.get("cmd"), str):
                continue
            try:
                paths.add(Path(self.codec.decode(entry["cmd"]).model_path))
            except CommandDecodeError:
                continue
        return paths

    def _ensure_allowed_path(self, path: Path) -> None:
        resolved = path.resolve(strict=False)
        if not any(resolved.is_relative_to(root) for root in self.allowed_roots):
            raise ServiceValidationError("Model path is outside the allowed model roots")
        if not resolved.exists():
            raise ServiceValidationError("Model path does not exist")

    def _ensure_immutable_command_fields(
        self, existing: CommentedMap, requested: Any
    ) -> None:
        command = existing.get("cmd")
        if not isinstance(command, str):
            raise ServiceValidationError("Existing model command is missing")
        try:
            current = self.codec.decode(command)
        except CommandDecodeError as error:
            raise ServiceValidationError(str(error)) from error
        immutable = ("backend", "launch_tokens", "model_argument", "port_token", "unknown_tokens")
        if any(getattr(current, key) != getattr(requested, key) for key in immutable):
            raise ServiceValidationError("Launcher and compatibility arguments are read-only")

    def _ensure_trusted_registration_template(
        self, snapshot: ConfigSnapshot, requested: Any
    ) -> None:
        immutable = ("backend", "launch_tokens", "model_argument", "port_token", "unknown_tokens")
        for entry in self._models(snapshot).values():
            if not isinstance(entry, CommentedMap) or not isinstance(entry.get("cmd"), str):
                continue
            try:
                current = self.codec.decode(entry["cmd"])
            except CommandDecodeError:
                continue
            if all(getattr(current, key) == getattr(requested, key) for key in immutable):
                return
        raise ServiceValidationError(
            "No trusted launcher template exists for this backend"
        )

    async def _confirm_hot_reload(self, model_id: str) -> None:
        deadline = time.monotonic() + self.reload_timeout
        while True:
            try:
                payload = await self.swap.models()
                if any(
                    isinstance(item, dict) and item.get("id") == model_id
                    for item in payload.get("data", [])
                ):
                    return
            except (SwapUnavailable, SwapResponseError):
                pass
            if time.monotonic() >= deadline:
                self.store.rollback_latest()
                raise ServiceHotReloadError(
                    f"llama-swap did not accept model {model_id!r}; configuration was restored"
                )
            await asyncio.sleep(self.poll_interval)
