from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
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
from .llm import LLMUnavailable
from .lab_client import LabClient, LabControllerUnavailable
from .models import ApprovalDecision, InvestigationRequest, LabRunRequest, QuestionRequest, utc_now
from .store import InMemoryStore, MongoStore, Store, approval_expired
from .workflow import InvestigationWorkflow, SCENARIOS


def _is_readable_evidence(document: dict[str, Any] | None) -> bool:
    return bool(document and document.get("evidence_version") in {2, 3})


def _is_executable_evidence(document: dict[str, Any] | None) -> bool:
    return bool(document and document.get("evidence_version") == 3)


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
        app.state.lab = LabClient(configured)
        app.state.settings = configured
        await app.state.workflow.reconcile(startup=True)
        watchdog = asyncio.create_task(app.state.workflow.watch_expiry())
        yield
        watchdog.cancel()
        await asyncio.gather(watchdog, return_exceptions=True)
        for task in app.state.workflow.tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*app.state.workflow.tasks.values(), return_exceptions=True)
        await selected_store.close()
        if checkpoint_client is not None:
            checkpoint_client.close()

    app = FastAPI(title="SREs Incident Response API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3001", "http://frontend:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    async def create_investigation_record(
        request: Request,
        body: InvestigationRequest,
        *,
        lab_run_id: str | None = None,
        scenario: str = "manual",
    ) -> dict[str, Any]:
        if not request.app.state.workflow.llm.enabled:
            raise HTTPException(status_code=503, detail="Groq is not configured. Set GROQ_API_KEY before starting an investigation.")
        now = utc_now()
        time_to = body.time_to or now
        time_from = body.time_from or (time_to - timedelta(minutes=5))
        if time_to > now + timedelta(seconds=5) or time_from >= time_to or time_to - time_from > timedelta(minutes=5):
            raise HTTPException(status_code=422, detail="Observation interval must be a valid UTC window of at most five minutes and cannot be in the future.")
        investigation_id = str(uuid.uuid4())
        workflow: InvestigationWorkflow = request.app.state.workflow
        await workflow.create(
            investigation_id,
            {
                "services": list(dict.fromkeys(body.services)),
                "symptom": body.symptom,
                "time_from": time_from,
                "time_to": time_to,
                "scenario": scenario,
            },
            lab_run_id,
        )
        if body.auto_start_investigation:
            workflow.start(investigation_id)
        return {
            "investigation_id": investigation_id,
            "scenario": scenario,
            "status": "started" if body.auto_start_investigation else "created",
            "agents": ["log", "metrics", "event", "correlation", "report"],
            "stream_url": f"/stream/investigation/{investigation_id}",
        }

    @app.post("/investigations", status_code=202)
    async def start_investigation(body: InvestigationRequest, request: Request) -> dict[str, Any]:
        return await create_investigation_record(request, body)

    @app.post("/lab/runs", status_code=202)
    async def launch_lab_run(body: LabRunRequest, request: Request) -> dict[str, Any]:
        if body.scenario not in SCENARIOS:
            raise HTTPException(status_code=404, detail="Scenario not found")
        if not request.app.state.workflow.llm.enabled:
            raise HTTPException(status_code=503, detail="Groq is not configured. No fault was introduced.")
        try:
            run = await request.app.state.lab.create_run(body.scenario, body.ttl_seconds)
        except LabControllerUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        scenario_context = {
            "redis-unavailable": (["api-server", "payment-service"], "Dependent application requests are returning errors."),
            "database-blocking": (["api-server"], "User retrieval requests are timing out or responding slowly."),
            "release-regression": (["api-server"], "The product operation is returning server errors."),
        }
        services, symptom = scenario_context[body.scenario]
        try:
            created = await create_investigation_record(
                request,
                InvestigationRequest(services=services, symptom=symptom, auto_start_investigation=body.auto_start_investigation),
                lab_run_id=run["run_id"],
                scenario=body.scenario,
            )
        except Exception:
            await request.app.state.lab.cleanup(run["run_id"])
            raise
        return {**created, "lab_run_id": run["run_id"], "expires_at": run["expires_at"]}

    @app.post("/investigation/{investigation_id}/cancel")
    async def cancel(investigation_id: str, request: Request) -> dict[str, str]:
        if not _is_readable_evidence(await request.app.state.store.get_investigation(investigation_id)):
            raise HTTPException(status_code=404, detail="Investigation not found")
        await request.app.state.workflow.cancel(investigation_id)
        return {"investigation_id": investigation_id, "status": "cancelled"}

    @app.get("/investigation/{investigation_id}")
    async def investigation(investigation_id: str, request: Request) -> dict[str, Any]:
        document = await request.app.state.store.get_investigation(investigation_id)
        if not _is_readable_evidence(document):
            raise HTTPException(status_code=404, detail="Investigation not found")
        agents = await request.app.state.store.list_agent_states(investigation_id)
        approvals = await request.app.state.store.list_approvals(investigation_id)
        questions = await request.app.state.store.list_questions(investigation_id)
        return {**document, "investigation_id": document["incident_id"], "agents": {agent["agent_name"]: agent for agent in agents}, "approvals": approvals, "questions": questions}

    @app.post("/investigation/{investigation_id}/questions", status_code=201)
    async def ask_question(investigation_id: str, body: QuestionRequest, request: Request) -> dict[str, Any]:
        if not _is_readable_evidence(await request.app.state.store.get_investigation(investigation_id)):
            raise HTTPException(status_code=404, detail="Investigation not found")
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=422, detail="Question must not be blank")
        try:
            return await request.app.state.workflow.answer_question(investigation_id, question)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Investigation not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except LLMUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/investigations")
    async def investigations(request: Request) -> dict[str, Any]:
        documents = await request.app.state.store.list_investigations()
        return {
            "investigations": [
                {
                    "investigation_id": document["incident_id"],
                    "scenario": document["scenario"],
                    "status": document["status"],
                    "created_at": document["created_at"],
                    "updated_at": document["updated_at"],
                    "completed_at": document.get("completed_at"),
                    "evidence_version": document["evidence_version"],
                }
                for document in documents
                if _is_readable_evidence(document)
            ]
        }

    @app.get("/approvals")
    async def approvals(request: Request, status: str | None = None) -> dict[str, Any]:
        documents = [document for document in await request.app.state.store.list_approvals() if _is_readable_evidence(document)]
        if status:
            documents = [document for document in documents if document["status"] == status]
        return {"approvals": documents}

    @app.get("/approvals/{approval_id}")
    async def approval(approval_id: str, request: Request) -> dict[str, Any]:
        document = await request.app.state.store.get_approval(approval_id)
        if not _is_readable_evidence(document):
            raise HTTPException(status_code=404, detail="Approval not found")
        return document

    @app.post("/investigation/{investigation_id}/approval/{approval_id}")
    async def decide(investigation_id: str, approval_id: str, body: ApprovalDecision, request: Request) -> dict[str, str]:
        document = await request.app.state.store.get_approval(approval_id)
        if not _is_executable_evidence(document) or document["investigation_id"] != investigation_id:
            raise HTTPException(status_code=404, detail="Approval not found")
        investigation = await request.app.state.store.get_investigation(investigation_id)
        if not _is_executable_evidence(investigation) or investigation["status"] != "awaiting_approval":
            raise HTTPException(status_code=409, detail="Investigation is not awaiting approval")
        if approval_expired(document):
            await request.app.state.workflow.reconcile()
            raise HTTPException(status_code=409, detail="Approval expired; collect fresh evidence before executing an operation")
        approved = body.decision == "approve"
        decision = "approved" if approved else "rejected"
        if not await request.app.state.workflow.resolve_approval(investigation_id, approval_id, decision):
            await request.app.state.workflow.reconcile()
            raise HTTPException(status_code=409, detail="Approval already decided or invalidated")
        return {"approval_id": approval_id, "status": decision, "investigation_id": investigation_id}

    @app.get("/stream/investigation/{investigation_id}")
    async def stream(investigation_id: str, request: Request) -> StreamingResponse:
        if not _is_readable_evidence(await request.app.state.store.get_investigation(investigation_id)):
            raise HTTPException(status_code=404, detail="Investigation not found")

        async def event_stream() -> AsyncIterator[str]:
            subscription = request.app.state.events.subscribe(investigation_id)
            next_event = asyncio.create_task(anext(subscription))
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(asyncio.shield(next_event), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                    except StopAsyncIteration:
                        break
                    else:
                        next_event = asyncio.create_task(anext(subscription))
                        yield f"data: {json.dumps(event, default=str)}\n\n"
                    if await request.is_disconnected():
                        break
            finally:
                if not next_event.done():
                    next_event.cancel()
                with suppress(asyncio.CancelledError, StopAsyncIteration):
                    await next_event
                with suppress(RuntimeError):
                    await subscription.aclose()

        return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/system/status")
    async def system_status(request: Request) -> dict[str, str]:
        settings = request.app.state.settings
        checks = {
            "sample_api": f"{settings.sample_api_url}/health",
            "sample_payment": f"{settings.sample_payment_url}/health",
            "prometheus": f"{settings.prometheus_url}/-/healthy",
            "loki": f"{settings.loki_url}/ready",
            "lab_controller": f"{settings.lab_controller_url}/health",
        }
        result: dict[str, str] = {"mongodb": await request.app.state.store.health(), "llm": "configured" if request.app.state.workflow.llm.enabled else "not_configured"}
        dependency_states: dict[str, list[str]] = {"redis": [], "postgres": []}
        async with httpx.AsyncClient(timeout=2) as client:
            for name, url in checks.items():
                try:
                    response = await client.get(url)
                    result[name] = "healthy" if response.is_success else "unhealthy"
                    if name.startswith("sample_"):
                        for dependency, value in response.json().get("dependencies", {}).items():
                            if dependency in dependency_states:
                                dependency_states[dependency].append(value)
                except httpx.HTTPError:
                    result[name] = "unreachable"
                except ValueError:
                    result[name] = "unknown"
        for dependency, values in dependency_states.items():
            expected = 2 if dependency == "redis" else 1
            result[dependency] = "unhealthy" if any(value != "healthy" for value in values) else "healthy" if len(values) == expected else "unknown"
        return result

    @app.post("/system/recover")
    async def recover(request: Request) -> dict[str, Any]:
        investigations = await request.app.state.store.list_investigations()
        if any(_is_executable_evidence(item) and item["status"] in {"investigating", "awaiting_approval"} for item in investigations):
            raise HTTPException(status_code=409, detail="Finish or cancel the active investigation before resetting the lab.")
        run_ids = list(dict.fromkeys(item.get("lab_run_id") for item in investigations if item.get("lab_run_id")))
        results = []
        for run_id in run_ids:
            try:
                results.append(await request.app.state.lab.cleanup(run_id))
            except LabControllerUnavailable as exc:
                if "not found" not in str(exc).lower():
                    raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"status": "reconciled", "runs": results}

    @app.get("/lab/runs/{run_id}")
    async def lab_run(run_id: str, request: Request) -> dict[str, Any]:
        try:
            return await request.app.state.lab.get_run(run_id)
        except LabControllerUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/lab/runs/{run_id}/cleanup")
    async def cleanup_lab_run(run_id: str, request: Request) -> dict[str, Any]:
        investigations = [item for item in await request.app.state.store.list_investigations() if item.get("lab_run_id") == run_id]
        for investigation in investigations:
            if investigation["status"] in {"investigating", "awaiting_approval"}:
                await request.app.state.workflow.cancel(investigation["incident_id"])
        try:
            cleaned = await request.app.state.lab.cleanup(run_id)
        except LabControllerUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        for investigation in investigations:
            await request.app.state.store.update_investigation(
                investigation["incident_id"],
                {"recovery_origin": cleaned.get("cleanup", {}).get("origin", "operator_cleanup")},
            )
        return cleaned

    return app


app = create_app()
