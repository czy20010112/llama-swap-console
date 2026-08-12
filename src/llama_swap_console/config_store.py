from __future__ import annotations

import hashlib
import io
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from filelock import FileLock
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError


class RevisionConflict(Exception):
    """The configuration changed after the caller read it."""


class ConfigValidationError(Exception):
    """The configuration cannot be parsed or safely mutated."""


@dataclass(frozen=True)
class ConfigSnapshot:
    document: CommentedMap
    revision: str
    raw: bytes
    backup_path: Path | None = None


class ConfigStore:
    def __init__(
        self, config_path: Path, backup_dir: Path, backup_limit: int = 20
    ) -> None:
        if backup_limit < 1:
            raise ValueError("backup_limit must be at least 1")
        self.config_path = Path(config_path)
        self.backup_dir = Path(backup_dir)
        self.backup_limit = backup_limit
        self._lock = FileLock(f"{self.config_path}.lock")
        self._yaml = YAML(typ="rt")
        self._yaml.preserve_quotes = True

    def read(self) -> ConfigSnapshot:
        with self._lock:
            return self._read_unlocked()

    def update_model(
        self, model_id: str, value: CommentedMap, revision: str
    ) -> ConfigSnapshot:
        def mutate(document: CommentedMap) -> None:
            models = self._models_mapping(document)
            if model_id not in models:
                raise ConfigValidationError(f"Model {model_id!r} does not exist")
            models[model_id] = value

        return self._mutate(revision, mutate)

    def register_model(
        self, model_id: str, value: CommentedMap, revision: str
    ) -> ConfigSnapshot:
        def mutate(document: CommentedMap) -> None:
            models = self._models_mapping(document)
            if model_id in models:
                raise ConfigValidationError(f"Model {model_id!r} already exists")
            models[model_id] = value

        return self._mutate(revision, mutate)

    def remove_model(self, model_id: str, revision: str) -> ConfigSnapshot:
        def mutate(document: CommentedMap) -> None:
            models = self._models_mapping(document)
            if model_id not in models:
                raise ConfigValidationError(f"Model {model_id!r} does not exist")
            del models[model_id]

        return self._mutate(revision, mutate)

    def restore(self, raw: bytes, *, expected_revision: str) -> ConfigSnapshot:
        with self._lock:
            current = self._read_unlocked()
            if current.revision != expected_revision:
                raise RevisionConflict("Configuration was modified externally")
            self._parse(raw)
            self._replace_with(raw)
            return self._read_unlocked()

    def discard_backup(self, backup_path: Path | None) -> None:
        if backup_path is None:
            return
        with self._lock:
            resolved = Path(backup_path).resolve(strict=False)
            backup_root = self.backup_dir.resolve(strict=False)
            if resolved.parent != backup_root:
                raise ConfigValidationError("Backup does not belong to this store")
            resolved.unlink(missing_ok=True)

    def rollback_latest(self) -> ConfigSnapshot:
        with self._lock:
            backups = sorted(self.backup_dir.glob("*-config.yaml"))
            if not backups:
                raise ConfigValidationError("No configuration backup is available")
            raw = backups[-1].read_bytes()
            self._parse(raw)
            self._replace_with(raw)
            return self._read_unlocked()

    def _mutate(
        self, revision: str, mutate: Callable[[CommentedMap], None]
    ) -> ConfigSnapshot:
        with self._lock:
            current = self._read_unlocked()
            if current.revision != revision:
                raise RevisionConflict("Configuration was modified externally")
            mutate(current.document)
            candidate = self._dump(current.document)
            self._parse(candidate)
            backup_path = self._backup(current.raw)
            self._replace_with(candidate)
            updated = self._read_unlocked()
            return ConfigSnapshot(
                document=updated.document,
                revision=updated.revision,
                raw=updated.raw,
                backup_path=backup_path,
            )

    def _read_unlocked(self) -> ConfigSnapshot:
        try:
            raw = self.config_path.read_bytes()
        except OSError as error:
            raise ConfigValidationError(f"Unable to read configuration: {error}") from error
        document = self._parse(raw)
        return ConfigSnapshot(
            document=document,
            revision=hashlib.sha256(raw).hexdigest(),
            raw=raw,
        )

    def _parse(self, raw: bytes) -> CommentedMap:
        try:
            document = self._yaml.load(raw.decode("utf-8"))
        except (UnicodeDecodeError, YAMLError) as error:
            raise ConfigValidationError(f"Unable to parse configuration: {error}") from error
        if not isinstance(document, CommentedMap):
            raise ConfigValidationError("Configuration root must be a mapping")
        return document

    @staticmethod
    def _models_mapping(document: CommentedMap) -> CommentedMap:
        models = document.get("models")
        if not isinstance(models, CommentedMap):
            raise ConfigValidationError("Configuration models node must be a mapping")
        return models

    def _dump(self, document: CommentedMap) -> bytes:
        stream = io.StringIO()
        self._yaml.dump(document, stream)
        return stream.getvalue().encode("utf-8")

    def _backup(self, raw: bytes) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        backup_path = self.backup_dir / f"{stamp}-config.yaml"
        with backup_path.open("wb") as backup:
            backup.write(raw)
            backup.flush()
            os.fsync(backup.fileno())
        backups = sorted(self.backup_dir.glob("*-config.yaml"))
        for expired in backups[: -self.backup_limit]:
            expired.unlink()
        return backup_path

    def _replace_with(self, raw: bytes) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        mode = self.config_path.stat().st_mode & 0o777 if self.config_path.exists() else 0o600
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.config_path.parent, prefix=f".{self.config_path.name}.",
                suffix=".tmp", delete=False
            ) as temporary:
                temporary.write(raw)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.chmod(temporary_path, mode)
            self._parse(temporary_path.read_bytes())
            os.replace(temporary_path, self.config_path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
