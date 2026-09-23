"""One HTTP service per agent. No queues, task history, or remote approval."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from threading import Lock
from uuid import uuid4

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .agent import Agent
from .approval import ApprovalRequired, ServiceApproval
from .config import load_config
from .errors import AgentError
from .llm_client import OllamaClient
from .logger import EventLogger
from .runtime import build_registry

MAX_BODY_BYTES = 32768
MAX_TASK_CHARS = 16000


def create_app(config=None, client_factory=OllamaClient, logger_factory=EventLogger):
    @asynccontextmanager
    async def lifespan(app):
        settings = config or load_config(os.environ.get("AGENT_CONFIG", "config/agent.yaml"))
        logger = logger_factory(settings.name)
        build_registry(settings, ServiceApproval(), logger)
        app.state.config = settings
        app.state.busy = Lock()
        app.state.probing = Lock()
        app.state.client = client_factory(settings.base_url, settings.model, settings.timeout)
        try:
            # Health checks never share the reasoning transport or its long timeout.
            app.state.probe = client_factory(settings.base_url, settings.model, 3)
            try:
                logger.emit("service_started")
                yield
            finally:
                app.state.probe.close()
        finally:
            app.state.client.close()
            logger.emit("service_stopped")

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_boundary(request, call_next):
        # Reject browser origins, including localhost origins. No browser UI exists.
        # Host validation also prevents DNS rebinding through an attacker's domain.
        host = request.headers.get("host", "").split(":", 1)[0].lower()
        if host not in {"127.0.0.1", "localhost"} or "origin" in request.headers:
            response = JSONResponse({"status": "error", "code": "local_clients_only"}, status_code=403)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def response(status, result, task_id=None, code=None, http_status=200):
        body = {"agent": app.state.config.name, "status": status, "result": result}
        if task_id is not None:
            body["task_id"] = task_id
        if code:
            body["code"] = code
        return JSONResponse(body, status_code=http_status)

    @app.get("/info")
    async def info():
        settings = app.state.config
        return {"agent": settings.name, "role": settings.role,
                "description": settings.description, "model": settings.model,
                "tools": list(settings.tools), "approval_policy": "interactive_cli_only"}

    def probe():
        if not app.state.probing.acquire(blocking=False):
            return JSONResponse({"agent": app.state.config.name, "status": "checking",
                                 "alive": True, "ollama": "checking"}, status_code=503)
        try:
            app.state.probe.verify()
            return {"agent": app.state.config.name, "status": "ok", "alive": True,
                    "ollama": "ready", "busy": app.state.busy.locked()}
        except AgentError as exc:
            return JSONResponse({"agent": app.state.config.name, "status": "degraded",
                                 "alive": True, "ollama": "unavailable", "code": exc.code},
                                status_code=503)
        except Exception:
            return JSONResponse({"agent": app.state.config.name, "status": "degraded",
                                 "alive": True, "ollama": "unavailable"}, status_code=503)
        finally:
            app.state.probing.release()

    @app.get("/health")
    async def health():
        return await anyio.to_thread.run_sync(probe)

    def run_task(task, task_id, logger):
        # The worker owns the lock until the loop finishes, even if the HTTP caller
        # disconnects. Never clear busy merely because a caller stopped waiting.
        try:
            registry = build_registry(app.state.config, ServiceApproval(), logger)
            agent = Agent(app.state.config, app.state.client, registry, logger,
                          writer=lambda message: None)
            result = agent.run(task)
            return response("completed", result, task_id)
        except ApprovalRequired as exc:
            return response("approval_required", str(exc), task_id, exc.code, 409)
        except AgentError as exc:
            logger.emit("agent_error", level="ERROR", error_code=exc.code)
            status = 503 if exc.code.startswith("llm_") or exc.code == "model_not_found" else 422
            return response("error", str(exc), task_id, exc.code, status)
        except Exception:
            logger.emit("agent_error", level="ERROR", error_code="internal_error")
            return response("error", "Unexpected task failure. See task ID in service logs.",
                            task_id, "internal_error", 500)
        finally:
            logger.emit("task_finished")
            app.state.busy.release()

    @app.post("/tasks")
    async def tasks(request: Request):
        task_id = str(uuid4())
        logger = logger_factory(app.state.config.name, task_id=task_id)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return response("error", "Use Content-Type: application/json.", task_id,
                            "invalid_content_type", 415)
        try:
            data = bytearray()
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > MAX_BODY_BYTES:
                        return response("error", "Request body exceeds 32 KiB.", task_id,
                                        "request_too_large", 413)
                    data.extend(chunk)
            payload = json.loads(data)
            if (not isinstance(payload, dict) or set(payload) != {"task"}
                    or not isinstance(payload["task"], str)
                    or not payload["task"].strip() or len(payload["task"]) > MAX_TASK_CHARS):
                raise ValueError
        except (ValueError, UnicodeError, RecursionError):
            return response("error", "Supply only a nonempty task string, at most 16000 characters.",
                            task_id, "invalid_task", 422)
        except TimeoutError:
            return response("error", "Request body timed out.", task_id, "request_timeout", 408)
        if not app.state.busy.acquire(blocking=False):
            logger.emit("task_busy")
            return response("busy", "Agent is processing another task. Try again later.",
                            task_id, "agent_busy", 409)
        # Shield scheduling as well as execution; the worker always releases busy.
        with anyio.CancelScope(shield=True):
            return await anyio.to_thread.run_sync(run_task, payload["task"], task_id, logger)

    return app


if __name__ == "__main__":
    import uvicorn

    # Exactly one process: multiple workers would each have an independent lock.
    uvicorn.run(create_app(), host="0.0.0.0", port=8000, workers=1,
                access_log=False, log_level="warning", proxy_headers=False)
