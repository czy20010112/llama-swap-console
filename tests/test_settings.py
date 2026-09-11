from __future__ import annotations

from pathlib import Path

import pytest


def _settings_type():
    try:
        from llama_swap_console.settings import Settings
    except ModuleNotFoundError:
        pytest.fail("Settings must be available from llama_swap_console.settings")

    return Settings


def test_settings_uses_expanded_default_paths_and_console_defaults() -> None:
    settings = _settings_type()()

    assert settings.config_path == Path("~/.config/llama-swap/config.yaml").expanduser()
    assert settings.model_roots == (Path("/mnt/d/AI/models"),)
    assert settings.llama_swap_url == "http://127.0.0.1:9292"
    assert settings.llama_swap_api_key == ""
    assert settings.listen_host == "127.0.0.1"
    assert settings.listen_port == 9293
    assert settings.backup_dir == Path(
        "~/.local/state/llama-swap-console/backups"
    ).expanduser()
    assert settings.backup_limit == 20


def test_settings_accepts_config_path_and_model_roots_at_construction(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    model_root = tmp_path / "models"

    settings = _settings_type()(
        config_path=config_path,
        model_roots=(model_root,),
    )

    assert settings.config_path == config_path
    assert settings.model_roots == (model_root,)


def test_settings_reads_prefixed_environment_variables_and_ignores_unknown_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLAMA_SWAP_CONSOLE_LISTEN_PORT", "9393")
    monkeypatch.setenv("LLAMA_SWAP_CONSOLE_UNRECOGNIZED", "ignored")

    settings = _settings_type()()

    assert settings.listen_port == 9393


def test_settings_reads_the_llama_swap_api_key_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLAMA_SWAP_CONSOLE_LLAMA_SWAP_API_KEY", "sk-test-only")

    settings = _settings_type()()

    assert settings.llama_swap_api_key == "sk-test-only"
