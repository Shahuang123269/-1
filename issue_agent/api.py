import asyncio
import hmac
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .config import Settings
from .domain import ApprovalRequest, DomainError, TaskRequest
from .engine import Engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        async with Engine(settings) as engine:
            app.state.engine = engine
            yield

    app = FastAPI(title="Issue Agent", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def access_boundary(request: Request, call_next):
        token = settings.api_token.get_secret_value()
        if request.url.path not in {"/", "/health"}:
            if token:
                received = request.headers.get("authorization", "")
                if not hmac.compare_digest(received, "Bearer " + token):
                    return JSONResponse({"error": "unauthorized"}, status_code=401)
            elif request.client and request.client.host not in {"127.0.0.1", "::1", "testclient"}:
                return JSONResponse({"error": "local_access_only"}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                return JSONResponse({"error": "cross_origin_blocked"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse(
            {"error": exc.code}, status_code=404 if exc.code == "not_found" else 409
        )

    @app.get("/", response_class=HTMLResponse)
    def index():
        return Path(__file__).with_name("ui.html").read_text(encoding="utf-8")

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "model_mode": settings.model_mode,
            "tool_mode": settings.tool_mode,
            "repository": settings.repository,
            "version": "0.1.0",
        }

    @app.post("/tasks", status_code=201)
    async def create(request: TaskRequest, idempotency_key: str | None = Header(None)):
        # V1 single executor: waits until investigation completes or approval pauses.
        return await app.state.engine.create(request, idempotency_key)

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str):
        return app.state.engine.store.task(task_id)

    @app.post("/tasks/{task_id}/approval")
    async def approve(task_id: str, request: ApprovalRequest):
        return await app.state.engine.approve(task_id, request.digest, request.decision)

    @app.post("/tasks/{task_id}/resume")
    async def resume(task_id: str):
        return await app.state.engine.resume(task_id)

    @app.get("/tasks/{task_id}/events")
    def events(task_id: str, after: int = 0):
        return app.state.engine.store.events(task_id, after)

    @app.get("/tasks/{task_id}/stream")
    async def stream(task_id: str, request: Request, last_event_id: str = Header("0")):
        app.state.engine.store.task(task_id)
        try:
            after = max(0, int(last_event_id))
        except ValueError:
            return JSONResponse({"error": "invalid_cursor"}, status_code=422)

        async def generate():
            nonlocal after
            while not await request.is_disconnected():
                for event in app.state.engine.store.events(task_id, after):
                    after = event["seq"]
                    yield f"id: {after}\nevent: task_event\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if app.state.engine.store.task(task_id)["status"] in {
                    "completed",
                    "failed",
                    "cancelled",
                    "awaiting_approval",
                    "reconciliation_needed",
                }:
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    return app
