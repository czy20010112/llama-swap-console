from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from llama_swap_console.api import install_error_handlers, local_origin_middleware, router
from llama_swap_console.command_codec import CommandCodec
from llama_swap_console.config_store import ConfigStore
from llama_swap_console.gpu_monitor import GpuMonitor
from llama_swap_console.model_scanner import ModelScanner
from llama_swap_console.model_service import ModelService
from llama_swap_console.settings import Settings
from llama_swap_console.swap_client import LlamaSwapClient


def create_app(
    settings: Settings | None = None, *, service: ModelService | None = None
) -> FastAPI:
    """Create the Console ASGI application."""

    resolved_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if service is not None:
            application.state.service = service
            yield
            return
        async with httpx.AsyncClient(base_url=resolved_settings.llama_swap_url) as client:
            application.state.service = ModelService(
                store=ConfigStore(
                    resolved_settings.config_path,
                    resolved_settings.backup_dir,
                    resolved_settings.backup_limit,
                ),
                codec=CommandCodec(),
                scanner=ModelScanner(resolved_settings.model_roots),
                swap=LlamaSwapClient(client),
                gpu=GpuMonitor(),
                allowed_roots=resolved_settings.model_roots,
            )
            yield

    application = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
    application.state.settings = resolved_settings
    application.middleware("http")(local_origin_middleware)
    application.include_router(router)
    install_error_handlers(application)

    web_root = Path(__file__).parent / "web"
    application.mount("/assets", StaticFiles(directory=web_root), name="assets")

    @application.get("/", include_in_schema=False)
    async def web_index():
        return FileResponse(web_root / "index.html")

    @application.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "llama-swap-console"}

    return application


app = create_app()
