from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

from .config import Settings, get_settings
from .events import EventHub
from .models import ApprovalDecision, Scenario, SettingsUpdate, SimulationRequest
from .store import InMemoryStore, MongoStore, Store
from .workflow import InvestigationWorkflow, SCENARIO_PROFILES


def create_app(settings: Settings | None = None, store: Store | None = None) -> FastAPI:
    configured = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        selected_store = store or (InMemoryStore() if configured.use_in_memory_store else MongoStore(configured.mongodb_url, configured.mongodb_database))
        await selected_store.initialize()
        checkpoint_client = None
        if configured.use_in_memory_store or isinstance(selected_store, InMemoryStore):
            checkpointer = InMemorySaver()
        else:
            checkpoint_client = MongoClient(configured.mongodb_url)
            checkpointer = MongoDBSaver(checkpoint_client, configured.mongodb_database)
        events = EventHub()
        app.state.store = selected_store
        app.state.events = events
        app.state.workflow = InvestigationWorkflow(selected_store, events, configured, checkpointer)
        app.state.settings = configured
        yield
        for task in app.state.workflow.tasks.values():
            if not task.done():
                task.cancel()
        await selected_store.close()
        if checkpoint_client is not None:
            checkpoint_client.close()

    app = FastAPI(title="SREs Incident Response API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://frontend:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    @app.post("/simulate/{scenario}", status_code=202)
    async def simulate(scenario: Scenario, body: SimulationRequest, request: Request) -> dict[str, Any]:
        if scenario not in SCENARIO_PROFILES:
            raise HTTPException(status_code=404, detail="Scenario not found")
        investigations = await request.app.state.store.list_investigations()
        if any(item["scenario"] == scenario and item["status"] in {"investigating", "awaiting_approval"} for item in investigations):
            raise HTTPException(status_code=409, detail="Investigation already running for this scenario")
        try:
            await _trigger_failure(request.app.state.settings, scenario)
        except httpx.HTTPError as exc:
            if request.app.state.settings.environment != "test":
                raise HTTPException(status_code=503, detail="Sample app not reachable") from exc
        investigation_id = str(uuid.uuid4())
        workflow: InvestigationWorkflow = request.app.state.workflow
        await workflow.create(investigation_id, scenario)
        if body.auto_start_investigation:
            workflow.start(investigation_id, scenario)
        return {
            "investigation_id": investigation_id,
            "scenario": scenario,
            "status": "started" if body.auto_start_investigation else "created",
            "agents": ["log", "metrics", "event", "correlation", "report"],
            "stream_url": f"/stream/investigation/{investigation_id}",
        }

    @app.post("/investigation/{investigation_id}/cancel")
    async def cancel(investigation_id: str, request: Request) -> dict[str, str]:
        if not await request.app.state.store.get_investigation(investigation_id):
            raise HTTPException(status_code=404, detail="Investigation not found")
        await request.app.state.workflow.cancel(investigation_id)
        return {"investigation_id": investigation_id, "status": "cancelled"}

    @app.get("/investigation/{investigation_id}")
    async def investigation(investigation_id: str, request: Request) -> dict[str, Any]:
        document = await request.app.state.store.get_investigation(investigation_id)
        if not document:
            raise HTTPException(status_code=404, detail="Investigation not found")
        agents = await request.app.state.store.list_agent_states(investigation_id)
        approvals = await request.app.state.store.list_approvals(investigation_id)
        return {**document, "investigation_id": document["incident_id"], "agents": {agent["agent_name"]: agent for agent in agents}, "approvals": approvals}

    @app.get("/investigations")
    async def investigations(request: Request) -> dict[str, Any]:
        documents = await request.app.state.store.list_investigations()
        return {"investigations": [{**doc, "investigation_id": doc["incident_id"]} for doc in documents]}

    @app.get("/approvals")
    async def approvals(request: Request, status: str | None = None) -> dict[str, Any]:
        documents = await request.app.state.store.list_approvals()
        if status:
            documents = [document for document in documents if document["status"] == status]
        return {"approvals": documents}

    @app.get("/approvals/{approval_id}")
    async def approval(approval_id: str, request: Request) -> dict[str, Any]:
        document = await request.app.state.store.get_approval(approval_id)
        if not document:
            raise HTTPException(status_code=404, detail="Approval not found")
        return document

    @app.post("/investigation/{investigation_id}/approval/{approval_id}")
    async def decide(investigation_id: str, approval_id: str, body: ApprovalDecision, request: Request) -> dict[str, str]:
        document = await request.app.state.store.get_approval(approval_id)
        if not document or document["investigation_id"] != investigation_id:
            raise HTTPException(status_code=404, detail="Approval not found")
        if document["status"] != "pending":
            raise HTTPException(status_code=409, detail="Approval already decided")
        approved = body.decision == "approve"
        asyncio.create_task(request.app.state.workflow.resume(investigation_id, approved))
        return {"approval_id": approval_id, "status": "approved" if approved else "rejected", "investigation_id": investigation_id}

    @app.get("/stream/investigation/{investigation_id}")
    async def stream(investigation_id: str, request: Request) -> StreamingResponse:
        if not await request.app.state.store.get_investigation(investigation_id):
            raise HTTPException(status_code=404, detail="Investigation not found")

        async def event_stream() -> AsyncIterator[str]:
            subscription = request.app.state.events.subscribe(investigation_id)
            while True:
                try:
                    event = await asyncio.wait_for(anext(subscription), timeout=15)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                if await request.is_disconnected():
                    break

        return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/system/status")
    async def system_status(request: Request) -> dict[str, str]:
        settings = request.app.state.settings
        checks = {
            "sample_api": f"{settings.sample_api_url}/health",
            "sample_payment": f"{settings.sample_payment_url}/health",
            "prometheus": f"{settings.prometheus_url}/-/healthy",
            "loki": f"{settings.loki_url}/ready",
        }
        result: dict[str, str] = {"mongodb": "healthy"}
        async with httpx.AsyncClient(timeout=2) as client:
            for name, url in checks.items():
                try:
                    response = await client.get(url)
                    result[name] = "healthy" if response.is_success else "unhealthy"
                except httpx.HTTPError:
                    result[name] = "unreachable"
        result["redis"] = "healthy" if result.get("sample_api") == "healthy" else "unknown"
        result["postgres"] = "healthy" if result.get("sample_api") == "healthy" else "unknown"
        return result

    @app.get("/settings")
    async def read_settings(request: Request) -> dict[str, Any]:
        settings = request.app.state.settings
        provider_keys = {
            "openai": settings.openai_api_key,
            "gemini": settings.gemini_api_key,
            "groq": settings.groq_api_key,
        }
        configured_key = provider_keys.get(settings.llm_provider, "")
        return {
            "llm_provider": settings.llm_provider,
            "api_key_configured": bool(configured_key),
            "environment": settings.environment,
        }

    @app.get("/settings/llm")
    async def read_llm_settings(request: Request) -> dict[str, Any]:
        settings = request.app.state.settings
        provider_keys = {
            "openai": settings.openai_api_key,
            "gemini": settings.gemini_api_key,
            "groq": settings.groq_api_key,
        }
        return {
            "llm_provider": settings.llm_provider,
            "api_key_configured": bool(provider_keys.get(settings.llm_provider, "")),
            "groq_model": settings.groq_model if settings.llm_provider == "groq" else None,
            "groq_reasoning_effort": settings.groq_reasoning_effort if settings.llm_provider == "groq" else None,
            "environment": settings.environment,
        }

    @app.post("/settings")
    async def update_settings(body: SettingsUpdate, request: Request) -> dict[str, Any]:
        settings = request.app.state.settings
        settings.llm_provider = body.llm_provider
        if body.api_key:
            if body.llm_provider == "openai":
                settings.openai_api_key = body.api_key
            elif body.llm_provider == "gemini":
                settings.gemini_api_key = body.api_key
            elif body.llm_provider == "groq":
                settings.groq_api_key = body.api_key
        request.app.state.workflow.llm = request.app.state.workflow.llm.__class__(settings)
        provider_keys = {
            "openai": settings.openai_api_key,
            "gemini": settings.gemini_api_key,
            "groq": settings.groq_api_key,
        }
        return {"llm_provider": settings.llm_provider, "api_key_configured": bool(provider_keys.get(settings.llm_provider, "")), "environment": settings.environment}

    @app.post("/system/recover")
    async def recover(request: Request) -> dict[str, str]:
        settings = request.app.state.settings
        async with httpx.AsyncClient(timeout=8) as client:
            calls = []
            for base in (settings.sample_api_url, settings.sample_payment_url):
                calls.extend(
                    [
                        client.post(f"{base}/api/simulate/redis-failure", json={"enabled": False}),
                        client.post(f"{base}/api/simulate/bad-deployment", json={"version": "v1"}),
                    ]
                )
            calls.append(client.post(f"{settings.sample_api_url}/api/simulate/slow-db", json={"enabled": False}))
            responses = await asyncio.gather(*calls, return_exceptions=True)
        if not any(isinstance(response, httpx.Response) and response.is_success for response in responses):
            raise HTTPException(status_code=503, detail="No sample service recovered")
        return {"status": "recovered"}

    return app


async def _trigger_failure(settings: Settings, scenario: str) -> None:
    if scenario == "redis-failure":
        path, payload, targets = "/api/simulate/redis-failure", {"enabled": True}, [settings.sample_api_url, settings.sample_payment_url]
    elif scenario == "slow-db":
        path, payload, targets = "/api/simulate/slow-db", {"enabled": True}, [settings.sample_api_url]
    else:
        path, payload, targets = "/api/simulate/bad-deployment", {"version": "v2"}, [settings.sample_api_url, settings.sample_payment_url]
    async with httpx.AsyncClient(timeout=8) as client:
        responses = await asyncio.gather(*(client.post(f"{target}{path}", json=payload) for target in targets))
        for response in responses:
            response.raise_for_status()


app = create_app()
