from __future__ import annotations

import asyncio
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from .config import Settings, get_settings
from .docker_ops import DockerOperations, StaleResource
from .models import OperationRequest, RunCompletionRequest, RunRequest
from .postgres_ops import PostgresOperations
from .store import ControlStore, utc_now


def require_monitor(request: Request, x_lab_token: str = Header(default="")) -> None:
    settings: Settings = request.app.state.settings
    if not (secrets.compare_digest(x_lab_token, settings.monitor_token) or secrets.compare_digest(x_lab_token, settings.operator_token)):
        raise HTTPException(status_code=401, detail="Invalid lab credential")


def require_operator(request: Request, x_lab_token: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_lab_token, request.app.state.settings.operator_token):
        raise HTTPException(status_code=401, detail="Invalid operator credential")


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = ControlStore(configured.mongodb_url, configured.mongodb_database)
        await store.initialize()
        app.state.settings = configured
        app.state.store = store
        app.state.docker = DockerOperations(configured)
        app.state.postgres = PostgresOperations(configured)
        app.state.mutation_lock = asyncio.Lock()
        await _reconcile_expired_runs(app)
        app.state.watchdog = asyncio.create_task(_watch_expiry(app))
        yield
        app.state.watchdog.cancel()
        await asyncio.gather(app.state.watchdog, return_exceptions=True)
        store.close()

    app = FastAPI(title="SREs Lab Controller", version="1.0.0", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    @app.get("/v1/resources/{resource_id}", dependencies=[Depends(require_monitor)])
    async def resource(resource_id: str, request: Request) -> dict[str, Any]:
        try:
            return await request.app.state.docker.inspect(resource_id)
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/database/blocking", dependencies=[Depends(require_monitor)])
    async def blocking(request: Request) -> dict[str, Any]:
        return {"observations": await request.app.state.postgres.inspect_blocking()}

    @app.get("/v1/releases/sample-api", dependencies=[Depends(require_monitor)])
    async def releases(request: Request) -> dict[str, Any]:
        current = await request.app.state.docker.inspect(configured.sample_api_service)
        return {"current": current, "history": await request.app.state.store.releases("sample-api")}

    @app.post("/v1/runs", status_code=201, dependencies=[Depends(require_operator)])
    async def create_run(body: RunRequest, request: Request) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        now = utc_now()
        expires_at = now + timedelta(seconds=min(body.ttl_seconds, configured.maximum_run_seconds))
        try:
            acquired = await request.app.state.store.acquire_lease(run_id, expires_at)
        except Exception as exc:
            if "duplicate key" in str(exc).lower():
                acquired = False
            else:
                raise
        if not acquired:
            raise HTTPException(status_code=409, detail="The shared lab already has an active run")
        document = {
            "run_id": run_id,
            "scenario": body.scenario,
            "status": "injecting",
            "created_at": now,
            "updated_at": now,
            "expires_at": expires_at,
            "fault": {},
            "cleanup": None,
        }
        await request.app.state.store.create_run(document)
        try:
            async with request.app.state.mutation_lock:
                if body.scenario == "redis-unavailable":
                    fault = await request.app.state.docker.stop_redis()
                elif body.scenario == "database-blocking":
                    fault = await request.app.state.postgres.create_blocker(run_id, body.ttl_seconds)
                else:
                    fault = await request.app.state.docker.deploy_regression()
                    await request.app.state.store.add_release({"service": "sample-api", "run_id": run_id, "from": fault["before"], "to": fault["after"], "observed_at": utc_now()})
            return await request.app.state.store.update_run(run_id, {"status": "active", "fault": fault})
        except Exception as exc:
            await request.app.state.store.update_run(run_id, {"status": "injection_failed", "error": str(exc)})
            await _cleanup_run(request.app, run_id, "failed_injection_cleanup")
            raise HTTPException(status_code=503, detail=f"Fault injection failed: {exc}") from exc

    @app.get("/v1/runs/{run_id}", dependencies=[Depends(require_operator)])
    async def get_run(run_id: str, request: Request) -> dict[str, Any]:
        document = await request.app.state.store.get_run(run_id)
        if not document:
            raise HTTPException(status_code=404, detail="Lab run not found")
        return document

    @app.post("/v1/runs/{run_id}/cleanup", dependencies=[Depends(require_operator)])
    async def cleanup(run_id: str, request: Request) -> dict[str, Any]:
        async with request.app.state.mutation_lock:
            return await _cleanup_run(request.app, run_id, "operator_cleanup")

    @app.post("/v1/runs/{run_id}/complete", dependencies=[Depends(require_operator)])
    async def complete_run(run_id: str, body: RunCompletionRequest, request: Request) -> dict[str, Any]:
        run = await request.app.state.store.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Lab run not found")
        status = "remediated" if body.verification_status == "verified" else "needs_cleanup"
        updated = await request.app.state.store.update_run(
            run_id,
            {
                "status": status,
                "cleanup": {
                    "origin": "agent_action",
                    "action_id": body.action_id,
                    "verification_status": body.verification_status,
                    "verification": body.verification,
                    "completed_at": utc_now(),
                },
            },
        )
        if status == "remediated":
            await request.app.state.store.release_lease(run_id)
        return updated

    @app.post("/v1/operations", status_code=202, dependencies=[Depends(require_operator)])
    async def operate(body: OperationRequest, request: Request) -> dict[str, Any]:
        now = utc_now()
        operation, created = await request.app.state.store.begin_operation(
            {
                **body.model_dump(),
                "status": "requested",
                "created_at": now,
                "updated_at": now,
                "result": None,
            }
        )
        if not created:
            return operation
        async with request.app.state.mutation_lock:
            await request.app.state.store.update_operation(body.action_id, {"status": "running"})
            try:
                parameters = body.parameters
                if body.action_type == "start_service":
                    result = await request.app.state.docker.start_service(parameters["resource_id"], parameters["expected_container_id"])
                elif body.action_type == "terminate_blocking_session":
                    result = await request.app.state.postgres.terminate_blocker(parameters["database"], int(parameters["pid"]), parameters["backend_start"])
                else:
                    result = await request.app.state.docker.rollback_release(
                        parameters["resource_id"],
                        parameters["expected_container_id"],
                        parameters["expected_current_image_id"],
                        parameters["previous_image_id"],
                    )
                    await request.app.state.store.add_release({"service": "sample-api", "action_id": body.action_id, "from": result["before"], "to": result["after"], "observed_at": utc_now()})
                return await request.app.state.store.update_operation(body.action_id, {"status": "succeeded", "result": result, "completed_at": utc_now()})
            except StaleResource as exc:
                return await request.app.state.store.update_operation(body.action_id, {"status": "stale", "error": str(exc), "completed_at": utc_now()})
            except ValueError as exc:
                return await request.app.state.store.update_operation(body.action_id, {"status": "failed", "error": str(exc), "completed_at": utc_now()})
            except Exception as exc:
                return await request.app.state.store.update_operation(body.action_id, {"status": "unknown", "error": str(exc), "completed_at": utc_now()})

    return app


async def _cleanup_run(app: FastAPI, run_id: str, origin: str) -> dict[str, Any]:
    run = await app.state.store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Lab run not found")
    if run["status"] in {"cleaned", "expired"}:
        return run
    try:
        if run["scenario"] == "redis-unavailable":
            current = await app.state.docker.inspect(app.state.settings.redis_service)
            result = {"status": "already_running", "observation": current} if current["running"] else await app.state.docker.start_service(app.state.settings.redis_service, current["container_id"])
        elif run["scenario"] == "database-blocking":
            result = await app.state.postgres.cleanup(run_id)
        else:
            current = await app.state.docker.inspect(app.state.settings.sample_api_service)
            ids = await app.state.docker.image_ids()
            result = {"status": "already_v1", "observation": current} if current["image_id"] == ids["v1"] else await app.state.docker.rollback_release(app.state.settings.sample_api_service, current["container_id"], current["image_id"], ids["v1"])
        status = "cleaned" if origin in {"operator_cleanup", "failed_injection_cleanup"} else "expired"
        updated = await app.state.store.update_run(run_id, {"status": status, "cleanup": {"origin": origin, "result": result, "completed_at": utc_now()}})
        await app.state.store.release_lease(run_id)
        return updated
    except Exception as exc:
        return await app.state.store.update_run(run_id, {"status": "needs_cleanup", "cleanup": {"origin": origin, "error": str(exc), "completed_at": utc_now()}})


async def _watch_expiry(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(10)
        await _reconcile_expired_runs(app)


async def _reconcile_expired_runs(app: FastAPI) -> None:
    now = utc_now()
    async for run in app.state.store.db.runs.find({"status": {"$in": ["injecting", "active"]}, "expires_at": {"$lte": now}}):
        async with app.state.mutation_lock:
            await _cleanup_run(app, run["run_id"], "automatic_cleanup")


app = create_app()
