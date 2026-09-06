from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_systemd_user_service_is_local_and_hardened() -> None:
    unit = (ROOT / "deploy" / "llama-swap-console.service").read_text(
        encoding="utf-8"
    )

    assert "%h/.local/share/llama-swap-console/.venv" in unit
    assert "--host 127.0.0.1" in unit
    assert "--port 9293" in unit
    assert "LLAMA_SWAP_CONSOLE_CONFIG_PATH=%h/.config/llama-swap/config.yaml" in unit
    assert "LLAMA_SWAP_CONSOLE_MODEL_ROOTS" in unit
    assert "/mnt/d/AI/models" in unit
    assert "/usr/lib/wsl/lib" in unit
    assert "/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0" in unit
    assert "Restart=on-failure" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit


def test_systemd_service_bounds_sse_shutdown_before_systemd_deadline() -> None:
    unit = (ROOT / "deploy" / "llama-swap-console.service").read_text(
        encoding="utf-8"
    )

    assert "--timeout-graceful-shutdown 10" in unit
    assert "TimeoutStopSec=20" in unit


def test_installer_is_idempotent_and_checks_health() -> None:
    script = (ROOT / "scripts" / "install-wsl.sh").read_text(encoding="utf-8")

    assert "python3 -m venv" in script
    assert "pip install" in script
    assert "command -v uv" in script
    assert "uv pip install" in script
    assert "--upgrade pip" not in script
    assert "systemctl --user daemon-reload" in script
    assert "systemctl --user enable --now llama-swap-console.service" in script
    assert "systemctl --user restart llama-swap-console.service" in script
    assert "http://127.0.0.1:9293/api/health" in script
    assert "http://localhost:9293" in script


def test_uninstaller_only_removes_the_owned_unit() -> None:
    script = (ROOT / "scripts" / "uninstall-wsl.sh").read_text(encoding="utf-8")

    assert "systemctl --user disable --now llama-swap-console.service" in script
    assert "realpath" in script
    assert "llama-swap-console.service" in script
    assert "rm -rf" not in script
    assert "/mnt/d/AI/models" not in script
    assert ".config/llama-swap/config.yaml" not in script


def test_readme_documents_recovery_and_data_retention() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for phrase in (
        "http://localhost:9293",
        "journalctl --user -u llama-swap-console",
        "端口占用",
        "Windows localhost 转发",
        "回滚",
        "不会删除模型文件",
        "不会删除 llama-swap 配置",
    ):
        assert phrase in readme
