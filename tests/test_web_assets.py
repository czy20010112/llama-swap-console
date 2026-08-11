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
