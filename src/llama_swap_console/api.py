from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from llama_swap_console.config_store import ConfigValidationError, RevisionConflict
from llama_swap_console.model_service import (
    ModelService,
    ServiceHotReloadError,
    ServiceNotFound,
    ServiceValidationError,
)
from llama_swap_console.schemas import ModelRegisterRequest, ModelUpdateRequest
from llama_swap_console.swap_client import (
    SwapResponseError,
    SwapUnauthorized,
    SwapUnavailable,
)


router = APIRouter(prefix="/api")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def service(request: Request) -> ModelService:
    return request.app.state.service


async def local_origin_middleware(request: Request, call_next):
    if request.method in _WRITE_METHODS:
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in _LOCAL_HOSTS:
            return JSONResponse(status_code=403, content={"detail": "External origins are forbidden"})
    return await call_next(request)


@router.get("/settings")
async def get_settings(request: Request):
    settings = request.app.state.settings
    return {
        "config_path": str(settings.config_path),
        "model_roots": [str(path) for path in settings.model_roots],
        "llama_swap_url": settings.llama_swap_url,
    }


@router.get("/models")
async def list_models(request: Request):
    return await service(request).list_models()


@router.get("/models/{model_id}")
async def get_model(model_id: str, request: Request):
    return await service(request).get_model(model_id)


@router.get("/models/{model_id}/speed")
async def model_speed(model_id: str, request: Request):
    return await service(request).decode_speed(model_id)


@router.put("/models/{model_id}")
async def update_model(model_id: str, body: ModelUpdateRequest, request: Request):
    return await service(request).update_model(model_id, body)


@router.post("/models/{model_id}/load")
async def load_model(model_id: str, request: Request):
    result = await service(request).load(model_id)
    content = {"result": result.result}
    if result.status is not None:
        content["status"] = result.status
    return JSONResponse(
        status_code=202 if result.accepted else 200,
        content=content,
    )


@router.post("/models/{model_id}/unload")
async def unload_model(model_id: str, request: Request):
    result = await service(request).unload(model_id)
    if result.accepted:
        return JSONResponse(
            status_code=202, content={"result": result.result, "status": result.status}
        )
    return {"result": result.result}


@router.post("/models/unload-all")
async def unload_all(request: Request):
    return {"result": await service(request).unload_all()}


@router.post("/scan")
async def scan(request: Request):
    return await service(request).scan()


@router.get("/discovered-models")
async def discovered(request: Request):
    return await service(request).discovered()


@router.post("/discovered-models/{candidate_id}/register")
async def register(candidate_id: str, body: ModelRegisterRequest, request: Request):
    return await service(request).register(candidate_id, body)


@router.get("/gpu")
async def gpu(request: Request):
    return await service(request).gpu_snapshot()


@router.get("/events")
async def events(request: Request):
    return StreamingResponse(
        service(request).swap.events(), media_type="text/event-stream"
    )


@router.get("/models/{model_id}/logs")
async def model_logs(model_id: str, request: Request):
    await service(request).get_model(model_id)
    return StreamingResponse(
        service(request).swap.events(), media_type="text/event-stream"
    )


@router.post("/config/rollback-latest")
async def rollback(request: Request):
    return await service(request).rollback_latest()


def install_error_handlers(app) -> None:
    @app.exception_handler(ServiceNotFound)
    async def not_found(_request, error: ServiceNotFound):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(RevisionConflict)
    async def conflict(_request, error: RevisionConflict):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    async def invalid(_request, error):
        return JSONResponse(status_code=422, content={"detail": str(error)})

    app.add_exception_handler(ServiceValidationError, invalid)
    app.add_exception_handler(ConfigValidationError, invalid)

    @app.exception_handler(SwapUnavailable)
    async def unavailable(_request, error: SwapUnavailable):
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.exception_handler(SwapUnauthorized)
    async def rejected_credential(_request, error: SwapUnauthorized):
        # 凭据被拒不是"上游出故障"，重试没有意义，必须让用户去改配置。
        return JSONResponse(
            status_code=503,
            content={"detail": str(error), "upstream_status": error.status},
        )

    @app.exception_handler(SwapResponseError)
    async def upstream_error(_request, error: SwapResponseError):
        return JSONResponse(
            status_code=502,
            content={"detail": str(error), "upstream_status": error.status},
        )

    @app.exception_handler(ServiceHotReloadError)
    async def reload_error(_request, error: ServiceHotReloadError):
        return JSONResponse(status_code=502, content={"detail": str(error)})
