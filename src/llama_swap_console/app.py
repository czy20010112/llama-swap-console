from __future__ import annotations

from fastapi import FastAPI

from llama_swap_console.settings import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the Console ASGI application."""

    application = FastAPI(docs_url=None, redoc_url=None)
    application.state.settings = settings or Settings()

    @application.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "llama-swap-console"}

    return application


app = create_app()
