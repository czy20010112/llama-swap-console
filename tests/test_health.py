from __future__ import annotations

import pytest
import httpx
from fastapi import FastAPI

from llama_swap_console.settings import Settings


def _create_app(settings: Settings | None = None):
    try:
        from llama_swap_console.app import create_app
    except ModuleNotFoundError:
        pytest.fail("create_app must be available from llama_swap_console.app")

    return create_app(settings)


@pytest.mark.asyncio
async def test_health_returns_console_service_status() -> None:
    transport = httpx.ASGITransport(app=_create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "llama-swap-console"}


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
@pytest.mark.asyncio
async def test_interactive_api_documentation_is_disabled(path: str) -> None:
    transport = httpx.ASGITransport(app=_create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(path)

    assert response.status_code == 404


def test_create_app_preserves_injected_settings_instance() -> None:
    settings = Settings(listen_port=9393)

    app = _create_app(settings)

    assert app.state.settings is settings


def test_module_exposes_default_app_for_uvicorn() -> None:
    try:
        from llama_swap_console.app import app
    except ImportError:
        pytest.fail("llama_swap_console.app must expose a module-level app")

    assert isinstance(app, FastAPI)
