from __future__ import annotations

import copy
import asyncio
import logging
import time
from collections.abc import Coroutine
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from ruamel.yaml.comments import CommentedMap

from llama_swap_console.command_codec import CommandCodec, CommandDecodeError
from llama_swap_console.config_store import ConfigSnapshot, ConfigStore
from llama_swap_console.model_scanner import DiscoveredModel, ModelScanner
from llama_swap_console.schemas import ModelRegisterRequest, ModelUpdateRequest
from llama_swap_console.swap_client import (
    SwapReadTimeout,
    SwapResponseError,
    SwapUnavailable,
)


logger = logging.getLogger(__name__)


class ServiceNotFound(Exception):
    pass


class ServiceValidationError(Exception):
    pass


class ServiceHotReloadError(Exception):
    pass


@dataclass(frozen=True)
class LifecycleResult:
    result: Any = None
    status: str | None = None

    @property
    def accepted(self) -> bool:
        return self.status in {"starting", "loading", "pending"}


class SwapProtocol(Protocol):
    async def models(self) -> Any: ...
    async def running(self) -> Any: ...
    async def load(self, model_id: str) -> Any: ...
    async def unload(self, model_id: str) -> Any: ...
    async def unload_all(self) -> Any: ...
    def events(self) -> Any: ...
    async def decode_speed(self, model_id: str) -> Any: ...


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
        hot_reload_settle_time: float = 1.0,
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
        self.hot_reload_settle_time = hot_reload_settle_time
        self._discovered: dict[str, DiscoveredModel] = {}
        self._scan_time = 0.0
        self._lifecycle_locks: dict[str, asyncio.Lock] = {}
        self._lifecycle_tasks: dict[str, asyncio.Task[LifecycleResult]] = {}
        self._lifecycle_operations: dict[str, str] = {}
        self._service_gate = asyncio.Lock()
        self._config_lock = asyncio.Lock()
        self._unload_all_task: asyncio.Task[None] | None = None

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
            try:
                running = await self.swap.running()
                for model_id in statuses:
                    running_status = self._status_from_running(running, model_id)
                    if running_status is not None:
                        statuses[model_id] = running_status
            except (SwapUnavailable, SwapResponseError):
                pass
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
        async with self._service_gate, self._config_lock:
            return await self._update_model(model_id, request)

    async def _update_model(
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
        updated = await self._update_existing_model_with_reload_barrier(
            model_id, entry, request.revision, snapshot.raw
        )
        if request.reload:
            await self._reload(model_id)
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
        age = time.monotonic() - self._scan_time if self._scan_time else None
        return {
            "models": [asdict(item) for item in self._discovered.values()],
            "scan_age_seconds": age,
            "scan_stale": age is not None and age > self.scan_ttl,
        }

    async def register(
        self, candidate_id: str, request: ModelRegisterRequest
    ) -> dict[str, Any]:
        async with self._service_gate, self._config_lock:
            return await self._register(candidate_id, request)

    async def _register(
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
        snapshot = self.store.read()
        self._ensure_trusted_registration_template(snapshot, request.settings)
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
        try:
            await self._confirm_hot_reload(request.model_id)
        except asyncio.CancelledError:
            try:
                await self._complete_transaction_recovery(
                    self._restore_registration_transaction(
                        snapshot, updated, request.model_id
                    )
                )
            except Exception as recovery_error:
                logger.critical(
                    "configuration recovery failed after cancelled model registration for %s",
                    request.model_id,
                    exc_info=(
                        type(recovery_error),
                        recovery_error,
                        recovery_error.__traceback__,
                    ),
                )
                raise asyncio.CancelledError() from recovery_error
            raise
        except Exception as error:
            try:
                cancellation_during_recovery = await self._complete_transaction_recovery(
                    self._restore_registration_transaction(snapshot, updated, request.model_id)
                )
            except Exception as recovery_error:
                raise ServiceHotReloadError(
                    f"Configuration recovery failed for model {request.model_id!r}"
                ) from recovery_error
            if cancellation_during_recovery:
                raise asyncio.CancelledError() from error
            raise
        self._discovered.pop(candidate_id, None)
        return self._detail(updated, request.model_id)

    async def load(self, model_id: str) -> LifecycleResult:
        while True:
            async with self._service_gate:
                self._require_model(self.store.read(), model_id)
                unload_all_task = self._unload_all_task
                if unload_all_task is None:
                    break
            await asyncio.shield(unload_all_task)
        return await self._run_lifecycle_operation(model_id, "load")

    async def unload(self, model_id: str) -> LifecycleResult:
        while True:
            async with self._service_gate:
                self._require_model(self.store.read(), model_id)
                unload_all_task = self._unload_all_task
                if unload_all_task is None:
                    break
            await asyncio.shield(unload_all_task)
        return await self._run_lifecycle_operation(model_id, "unload")

    async def unload_all(self) -> Any:
        async with self._service_gate:
            task = self._unload_all_task
            if task is None or task.done():
                model_ids = tuple(self._models(self.store.read()))
                task = asyncio.create_task(self._unload_all_models(model_ids))
                self._unload_all_task = task
                task.add_done_callback(self._complete_unload_all_task)
        return await asyncio.shield(task)

    async def _unload_all_models(self, model_ids: tuple[str, ...]) -> None:
        results = await asyncio.gather(
            *(self._run_lifecycle_operation(model_id, "unload") for model_id in model_ids),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result

    def _complete_unload_all_task(self, task: asyncio.Task[None]) -> None:
        try:
            error = task.exception()
        except asyncio.CancelledError:
            error = None
        if error is not None:
            logger.error(
                "llama-swap unload-all operation failed",
                exc_info=(type(error), error, error.__traceback__),
            )
        if self._unload_all_task is task:
            self._unload_all_task = None

    async def gpu_snapshot(self) -> dict[str, Any]:
        return asdict(await self.gpu.sample())

    async def decode_speed(self, model_id: str) -> dict[str, Any]:
        self._require_model(self.store.read(), model_id)
        return await self.swap.decode_speed(model_id)

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
        immutable = ("backend", "launch_tokens", "model_argument", "port_token")
        if any(getattr(current, key) != getattr(requested, key) for key in immutable):
            raise ServiceValidationError("Launcher and compatibility arguments are read-only")

    def _ensure_trusted_registration_template(
        self, snapshot: ConfigSnapshot, requested: Any
    ) -> None:
        immutable = ("backend", "launch_tokens", "model_argument", "port_token")
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

    async def _load_upstream(self, model_id: str) -> LifecycleResult:
        try:
            result = await self.swap.load(model_id)
        except SwapReadTimeout:
            status = await self._confirmed_load_status(model_id)
            if status is not None:
                return LifecycleResult(status=status)
            raise
        if result is not None:
            return LifecycleResult(result=result)
        status = await self._confirmed_load_status(model_id)
        if status is not None:
            return LifecycleResult(status=status)
        return LifecycleResult(status="pending")

    async def _confirmed_load_status(self, model_id: str) -> str | None:
        try:
            status = await self._running_status(model_id)
        except (SwapUnavailable, SwapResponseError):
            status = None
        if self._is_starting(status) or self._is_active(status):
            return status
        try:
            status = await self._model_status(model_id)
        except (SwapUnavailable, SwapResponseError):
            status = None
        if self._is_starting(status) or self._is_active(status):
            return status
        return None

    async def _reload(self, model_id: str) -> LifecycleResult:
        await self._run_lifecycle_operation(model_id, "unload")
        return await self._run_lifecycle_operation(model_id, "load")

    async def _model_status(self, model_id: str) -> str | None:
        payload = await self.swap.models()
        for item in payload.get("data", []):
            if isinstance(item, dict) and item.get("id") == model_id:
                status = item.get("status")
                if isinstance(status, dict):
                    value = status.get("value")
                    return str(value).lower() if value is not None else None
                if isinstance(status, str):
                    return status.lower()
        return None

    async def _running_status(self, model_id: str) -> str | None:
        payload = await self.swap.running()
        return self._status_from_running(payload, model_id)

    @staticmethod
    def _status_from_running(payload: Any, model_id: str) -> str | None:
        if not isinstance(payload, dict):
            return None
        running = payload.get("running", payload)
        if isinstance(running, dict):
            entry = running.get(model_id)
            if isinstance(entry, dict):
                value = entry.get("state", entry.get("status"))
                return str(value).lower() if value is not None else None
        if isinstance(running, list):
            for entry in running:
                if not isinstance(entry, dict):
                    continue
                entry_id = entry.get("model", entry.get("id", entry.get("name")))
                if entry_id != model_id:
                    continue
                value = entry.get("state", entry.get("status"))
                return str(value).lower() if value is not None else None
        return None

    @staticmethod
    def _is_starting(status: str | None) -> bool:
        return status in {"starting", "loading"}

    @staticmethod
    def _is_active(status: str | None) -> bool:
        return status in {"ready", "running", "loaded"}

    def _discard_lifecycle_lock(self, model_id: str, lock: asyncio.Lock) -> None:
        if not lock.locked() and self._lifecycle_locks.get(model_id) is lock:
            self._lifecycle_locks.pop(model_id, None)

    async def _run_lifecycle_operation(
        self, model_id: str, operation: str
    ) -> LifecycleResult:
        while True:
            task = self._lifecycle_tasks.get(model_id)
            if task is not None:
                if self._lifecycle_operations.get(model_id) == operation:
                    return LifecycleResult(status="starting")
                await asyncio.shield(task)
                continue

            status = await self._model_status(model_id)
            if operation == "load" and self._is_starting(status):
                return LifecycleResult(status="starting")
            if operation == "load" and self._is_active(status):
                return LifecycleResult(status=status)

            lock = self._lifecycle_locks.setdefault(model_id, asyncio.Lock())
            created_task = False
            try:
                async with lock:
                    task = self._lifecycle_tasks.get(model_id)
                    if task is not None:
                        continue

                    status = await self._model_status(model_id)
                    if operation == "load" and self._is_starting(status):
                        return LifecycleResult(status="starting")
                    if operation == "load" and self._is_active(status):
                        return LifecycleResult(status=status)

                    task = self._start_lifecycle_task(model_id, lock, operation)
                    created_task = True
            finally:
                if not created_task and self._lifecycle_tasks.get(model_id) is None:
                    self._discard_lifecycle_lock(model_id, lock)

            return await asyncio.shield(task)

    def _start_lifecycle_task(
        self, model_id: str, lock: asyncio.Lock, operation: str
    ) -> asyncio.Task[LifecycleResult]:
        operation_call = self._load_upstream if operation == "load" else self._unload_upstream
        task = asyncio.create_task(operation_call(model_id))
        self._lifecycle_tasks[model_id] = task
        self._lifecycle_operations[model_id] = operation
        task.add_done_callback(
            lambda completed: self._complete_lifecycle_task(model_id, lock, completed)
        )
        return task

    async def _unload_upstream(self, model_id: str) -> LifecycleResult:
        return LifecycleResult(result=await self.swap.unload(model_id))

    def _complete_lifecycle_task(
        self, model_id: str, lock: asyncio.Lock, task: asyncio.Task[LifecycleResult]
    ) -> None:
        try:
            error = task.exception()
        except asyncio.CancelledError:
            error = None
        if error is not None:
            logger.error(
                "llama-swap %s operation for %s failed",
                self._lifecycle_operations.get(model_id, "lifecycle"),
                model_id,
                exc_info=(type(error), error, error.__traceback__),
            )
        if self._lifecycle_tasks.get(model_id) is task:
            self._lifecycle_tasks.pop(model_id, None)
            self._lifecycle_operations.pop(model_id, None)
        self._discard_lifecycle_lock(model_id, lock)

    async def _update_existing_model_with_reload_barrier(
        self, model_id: str, entry: CommentedMap, revision: str, original_raw: bytes
    ) -> ConfigSnapshot:
        original = ConfigSnapshot(
            document=self.store.read().document, revision=revision, raw=original_raw
        )
        removed: ConfigSnapshot | None = None
        result: ConfigSnapshot | None = None
        try:
            removed = self.store.remove_model(model_id, revision)
            await self._confirm_hot_reload(model_id, expected_present=False)
            result = self.store.register_model(model_id, entry, removed.revision)
            await self._confirm_hot_reload(model_id, expected_present=True)
        except asyncio.CancelledError:
            if removed is None:
                raise
            try:
                await self._complete_transaction_recovery(
                    self._restore_update_transaction(original, removed, result, model_id)
                )
            except Exception as recovery_error:
                logger.critical(
                    "configuration recovery failed after cancelled model update for %s",
                    model_id,
                    exc_info=(
                        type(recovery_error),
                        recovery_error,
                        recovery_error.__traceback__,
                    ),
                )
                raise asyncio.CancelledError() from recovery_error
            raise
        except Exception as error:
            if removed is None:
                raise
            try:
                cancellation_during_recovery = await self._complete_transaction_recovery(
                    self._restore_update_transaction(original, removed, result, model_id)
                )
            except Exception as recovery_error:
                raise ServiceHotReloadError(
                    f"Configuration recovery failed for model {model_id!r}"
                ) from recovery_error
            if cancellation_during_recovery:
                raise asyncio.CancelledError() from error
            raise
        self.store.discard_backup(result.backup_path)
        return result

    async def _restore_registration_transaction(
        self, original: ConfigSnapshot, updated: ConfigSnapshot, model_id: str
    ) -> None:
        await self._restore_and_confirm(
            original,
            expected_revision=updated.revision,
            model_id=model_id,
            expected_present=False,
        )
        self.store.discard_backup(updated.backup_path)

    async def _restore_update_transaction(
        self,
        original: ConfigSnapshot,
        removed: ConfigSnapshot,
        result: ConfigSnapshot | None,
        model_id: str,
    ) -> None:
        current_revision = result.revision if result is not None else removed.revision
        await self._restore_and_confirm(
            original,
            expected_revision=current_revision,
            model_id=model_id,
            expected_present=True,
        )
        if result is not None:
            self.store.discard_backup(result.backup_path)
        self.store.discard_backup(removed.backup_path)

    async def _complete_transaction_recovery(
        self, recovery: Coroutine[Any, Any, None]
    ) -> bool:
        """Finish a rollback even if the request receives additional cancellation."""
        task = asyncio.create_task(recovery)
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
        task.result()
        return cancelled

    async def _restore_and_confirm(
        self,
        original: ConfigSnapshot,
        *,
        expected_revision: str,
        model_id: str,
        expected_present: bool,
    ) -> None:
        self.store.restore(original.raw, expected_revision=expected_revision)
        try:
            await self._confirm_hot_reload(model_id, expected_present=expected_present)
        except ServiceHotReloadError as error:
            raise ServiceHotReloadError(
                f"Configuration was restored, but llama-swap recovery for model "
                f"{model_id!r} was not confirmed"
            ) from error

    async def _confirm_hot_reload(
        self, model_id: str, *, expected_present: bool = True
    ) -> None:
        deadline = time.monotonic() + self.reload_timeout
        while True:
            try:
                status = await self._model_status(model_id)
                if (status is not None) == expected_present:
                    return
            except (SwapUnavailable, SwapResponseError):
                pass
            if time.monotonic() >= deadline:
                raise ServiceHotReloadError(
                    f"llama-swap did not observe model {model_id!r} as "
                    f"{'present' if expected_present else 'absent'}"
                )
            await asyncio.sleep(self.poll_interval)
