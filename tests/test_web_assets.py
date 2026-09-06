from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from llama_swap_console.app import create_app
from llama_swap_console.settings import Settings


def test_spa_and_local_assets_are_served(tmp_path: Path) -> None:
    settings = Settings(config_path=tmp_path / "config.yaml", model_roots=(tmp_path,))

    with TestClient(create_app(settings)) as client:
        page = client.get("/")
        script = client.get("/assets/app.js")
        styles = client.get("/assets/styles.css")

    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert script.status_code == 200
    assert styles.status_code == 200
    assert "https://" not in page.text
    assert "/assets/app.js" in page.text
    assert "/assets/styles.css" in page.text


def test_html_has_operational_landmarks_and_edit_dialog(tmp_path: Path) -> None:
    settings = Settings(config_path=tmp_path / "config.yaml", model_roots=(tmp_path,))

    with TestClient(create_app(settings)) as client:
        html = client.get("/").text

    assert 'id="model-nav"' in html
    assert 'id="model-detail"' in html
    assert 'id="operations-panel"' in html
    assert 'id="model-editor"' in html
    assert '<dialog' in html
    assert 'id="language-toggle"' in html
    assert 'aria-live="polite"' in html
    assert 'id="decode-speed"' in html


def test_javascript_contains_complete_locale_roots() -> None:
    script = (
        Path(__file__).parents[1]
        / "src"
        / "llama_swap_console"
        / "web"
        / "app.js"
    ).read_text(encoding="utf-8")

    assert '"zh-CN"' in script
    assert '"en"' in script
    assert "localStorage" in script


def test_javascript_has_bounded_starting_state_polling() -> None:
    script = (
        Path(__file__).parents[1]
        / "src"
        / "llama_swap_console"
        / "web"
        / "app.js"
    ).read_text(encoding="utf-8")

    assert "OPERATION_STATUS_MAX_POLLS" in script
    assert "waitForOperationStatus" in script
    assert '["starting", "loading", "pending"].includes(operation.status)' in script
    assert '["running", "loaded", "ready", "starting", "loading", "pending"]' in script
    assert 'const transitioning = ["starting", "loading", "pending"].includes(status);' in script


def test_javascript_does_not_poll_expensive_gpu_processes_every_two_seconds() -> None:
    script = (
        Path(__file__).parents[1]
        / "src"
        / "llama_swap_console"
        / "web"
        / "app.js"
    ).read_text(encoding="utf-8")

    assert "const GPU_REFRESH_MS = 15_000;" in script
    assert "setInterval(() => { if (!document.hidden) loadGpu(); }, GPU_REFRESH_MS);" in script


def test_javascript_polls_and_labels_pure_decode_speed() -> None:
    script = (
        Path(__file__).parents[1]
        / "src"
        / "llama_swap_console"
        / "web"
        / "app.js"
    ).read_text(encoding="utf-8")

    assert "const SPEED_REFRESH_MS = 2_000;" in script
    assert "async function loadDecodeSpeed()" in script
    assert 'api(`/api/models/${encodeURIComponent(model.id)}/speed`)' in script
    assert 'setInterval(() => { if (!document.hidden) loadDecodeSpeed(); }, SPEED_REFRESH_MS);' in script


def test_javascript_batches_and_bounds_live_log_rendering() -> None:
    script = (
        Path(__file__).parents[1]
        / "src"
        / "llama_swap_console"
        / "web"
        / "app.js"
    ).read_text(encoding="utf-8")

    assert "const MAX_LOG_LINES = 2_000;" in script
    assert "const MAX_LOG_CHARS = 120_000;" in script
    assert "const MAX_LOG_EVENT_CHARS = 12_000;" in script
    assert "function eventText(event)" in script
    assert "function scheduleLogFlush()" in script
    assert 'state.logPending.push(...text.split("\\n"));' in script
    assert "view.textContent = state.logLines.join(\"\\n\");" in script
    assert "view.textContent}${event.data}" not in script


def test_sse_endpoint_does_not_intentionally_disconnect_every_few_seconds() -> None:
    api = (
        Path(__file__).parents[1]
        / "src"
        / "llama_swap_console"
        / "api.py"
    ).read_text(encoding="utf-8")

    assert "_bounded_event_stream" not in api
    assert "service(request).swap.events()" in api
