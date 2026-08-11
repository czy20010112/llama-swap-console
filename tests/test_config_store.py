from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml.comments import CommentedMap

from llama_swap_console.config_store import (
    ConfigStore,
    ConfigValidationError,
    RevisionConflict,
)


SOURCE = b"""# keep this comment
models:
  alpha:
    cmd: old-command
groups:
  writing:
    members: [alpha]
"""


def make_store(tmp_path: Path, *, backup_limit: int = 20) -> tuple[ConfigStore, Path, Path]:
    config_path = tmp_path / "config.yaml"
    backup_dir = tmp_path / "backups"
    config_path.write_bytes(SOURCE)
    return ConfigStore(config_path, backup_dir, backup_limit), config_path, backup_dir


def test_read_returns_round_trip_document_and_sha256_revision(tmp_path: Path) -> None:
    store, _, _ = make_store(tmp_path)

    snapshot = store.read()

    assert isinstance(snapshot.document, CommentedMap)
    assert snapshot.document["models"]["alpha"]["cmd"] == "old-command"
    assert len(snapshot.revision) == 64
    assert snapshot.raw == SOURCE


def test_update_model_preserves_comments_and_unrelated_nodes(tmp_path: Path) -> None:
    store, config_path, backup_dir = make_store(tmp_path)
    original = store.read()

    updated = store.update_model(
        "alpha",
        CommentedMap({"cmd": "new-command", "ttl": 60}),
        original.revision,
    )

    raw = config_path.read_text(encoding="utf-8")
    assert raw.startswith("# keep this comment\n")
    assert updated.document["models"]["alpha"]["cmd"] == "new-command"
    assert updated.document["groups"] == {"writing": {"members": ["alpha"]}}
    backups = list(backup_dir.glob("*-config.yaml"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == SOURCE


def test_update_rejects_stale_revision_without_writing_or_backup(tmp_path: Path) -> None:
    store, config_path, backup_dir = make_store(tmp_path)

    with pytest.raises(RevisionConflict):
        store.update_model("alpha", CommentedMap({"cmd": "new"}), "0" * 64)

    assert config_path.read_bytes() == SOURCE
    assert not backup_dir.exists()


def test_register_model_requires_new_id_and_models_mapping(tmp_path: Path) -> None:
    store, config_path, _ = make_store(tmp_path)
    snapshot = store.read()

    with pytest.raises(ConfigValidationError, match="already exists"):
        store.register_model("alpha", CommentedMap({"cmd": "new"}), snapshot.revision)

    config_path.write_text("models: []\n", encoding="utf-8")
    malformed = store.read()
    with pytest.raises(ConfigValidationError, match="models.*mapping"):
        store.register_model("beta", CommentedMap({"cmd": "new"}), malformed.revision)


def test_register_model_adds_entry_without_changing_existing_entry(tmp_path: Path) -> None:
    store, _, _ = make_store(tmp_path)
    snapshot = store.read()

    result = store.register_model(
        "beta", CommentedMap({"cmd": "beta-command"}), snapshot.revision
    )

    assert result.document["models"]["alpha"]["cmd"] == "old-command"
    assert result.document["models"]["beta"]["cmd"] == "beta-command"


def test_backup_retention_keeps_newest_limit(tmp_path: Path) -> None:
    store, _, backup_dir = make_store(tmp_path, backup_limit=3)

    for index in range(5):
        snapshot = store.read()
        store.update_model(
            "alpha", CommentedMap({"cmd": f"command-{index}"}), snapshot.revision
        )

    backups = sorted(backup_dir.glob("*-config.yaml"))
    assert len(backups) == 3
    assert b"command-0" not in backups[0].read_bytes()
    assert b"command-1" in backups[0].read_bytes()


def test_rollback_latest_restores_exact_previous_bytes(tmp_path: Path) -> None:
    store, config_path, _ = make_store(tmp_path)
    snapshot = store.read()
    store.update_model("alpha", CommentedMap({"cmd": "changed"}), snapshot.revision)

    restored = store.rollback_latest()

    assert config_path.read_bytes() == SOURCE
    assert restored.raw == SOURCE


def test_rollback_without_backup_is_explicit_error(tmp_path: Path) -> None:
    store, _, _ = make_store(tmp_path)

    with pytest.raises(ConfigValidationError, match="No configuration backup"):
        store.rollback_latest()


def test_invalid_yaml_is_rejected_on_read(tmp_path: Path) -> None:
    store, config_path, _ = make_store(tmp_path)
    config_path.write_text("models: [\n", encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="parse"):
        store.read()
