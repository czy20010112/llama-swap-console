from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the Console service."""

    model_config = SettingsConfigDict(
        env_prefix="LLAMA_SWAP_CONSOLE_",
        extra="ignore",
    )

    config_path: Path = Path("~/.config/llama-swap/config.yaml").expanduser()
    model_roots: tuple[Path, ...] = (Path("/mnt/d/AI/models"),)
    llama_swap_url: str = "http://127.0.0.1:9292"
    # Bearer token for llama-swap when it runs behind API-key auth.
    # Keep it in the environment, never in version control.
    llama_swap_api_key: str = ""
    listen_host: str = "127.0.0.1"
    listen_port: int = 9293
    backup_dir: Path = Path("~/.local/state/llama-swap-console/backups").expanduser()
    backup_limit: int = 20
