from __future__ import annotations

import asyncio
import json
import os
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from release_behavior import product_payload


SERVICE_KIND = os.getenv("SERVICE_KIND", "api")
SERVICE_NAME = "api-server" if SERVICE_KIND == "api" else "payment-service"
LOKI_URL = os.getenv("LOKI_URL", "http://localhost:3100")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://postgres:postgres@localhost:5432/incident_db")

registry = CollectorRegistry()
HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["service", "endpoint", "method", "status"], registry=registry)
HTTP_DURATION = Histogram("http_request_duration_seconds", "HTTP request latency", ["service", "endpoint"], registry=registry)
REDIS_CONNECTIONS = Counter("redis_connections_total", "Redis connection attempts", ["service", "result"], registry=registry)
REDIS_ACTIVE = Gauge("redis_connections_active", "Whether Redis is reachable", ["service"], registry=registry)
POSTGRES_QUERIES = Counter("postgres_queries_total", "Postgres queries", ["service", "result"], registry=registry)
POSTGRES_DURATION = Histogram("postgres_query_duration_seconds", "Postgres query latency", ["service"], registry=registry)
PAYMENTS_PROCESSED = Counter("payments_processed_total", "Processed payments", ["service"], registry=registry)
PAYMENTS_FAILED = Counter("payments_failed_total", "Failed payments", ["service"], registry=registry)


class Payment(BaseModel):
    amount: float
    currency: str = "USD"


async def ship_log(level: str, message: str, **fields: Any) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": level,
        "service": SERVICE_NAME,
        "message": message,
        "trace_id": fields.pop("trace_id", uuid.uuid4().hex[:16]),
        **fields,
    }
    body = {
        "streams": [
            {
                "stream": {"service": SERVICE_NAME, "level": level},
                "values": [[str(time.time_ns()), json.dumps(payload)]],
            }
        ]
    }
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.post(f"{LOKI_URL}/loki/api/v1/push", json=body)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logging.getLogger(__name__).warning("Log delivery failed: %s", exc)


async def lab_traffic() -> None:
    """Generate real HTTP requests; only request handlers record measured telemetry."""
    port = os.getenv("PORT", "8001" if SERVICE_KIND == "api" else "8002")
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=15, headers={"X-Traffic-Source": "lab-workload"}) as client:
        while True:
            calls = [client.get("/api/users"), client.get("/api/products")] if SERVICE_KIND == "api" else [client.post("/api/payments", json={"amount": 1, "currency": "USD"})]
            results = await asyncio.gather(*calls, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logging.getLogger(__name__).warning("Lab request failed: %s", result)
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
    try:
        app.state.postgres = await asyncpg.create_pool(POSTGRES_URL, min_size=1, max_size=3)
    except Exception as exc:
        logging.getLogger(__name__).error("PostgreSQL connection failed: %s", exc)
        app.state.postgres = None
    task = asyncio.create_task(lab_traffic())
    yield
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await app.state.redis.aclose()
    if app.state.postgres:
        await app.state.postgres.close()


app = FastAPI(title=f"SREs sample {SERVICE_NAME}", lifespan=lifespan)


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    if request.url.path in {"/metrics", "/health", "/live"}:
        return await call_next(request)
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as exc:
        await ship_log("ERROR", f"Request failed: {type(exc).__name__}: {exc}", path=request.url.path)
        response = JSONResponse({"detail": "Dependency request failed"}, status_code=503)
    duration = time.monotonic() - started
    HTTP_REQUESTS.labels(SERVICE_NAME, request.url.path, request.method, str(response.status_code)).inc()
    HTTP_DURATION.labels(SERVICE_NAME, request.url.path).observe(duration)
    level = "ERROR" if response.status_code >= 500 else "INFO"
    await ship_log(level, f"{request.method} {request.url.path} {response.status_code} {duration * 1000:.0f}ms", method=request.method, path=request.url.path, status=response.status_code, duration_ms=round(duration * 1000, 2), traffic_source=request.headers.get("X-Traffic-Source", "external"))
    return response


@app.get("/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    dependencies = {}
    try:
        await request.app.state.redis.ping()
        dependencies["redis"] = "healthy"
    except Exception:
        dependencies["redis"] = "unreachable"
    if SERVICE_KIND == "api":
        try:
            if not request.app.state.postgres:
                raise RuntimeError("PostgreSQL pool unavailable")
            async with request.app.state.postgres.acquire(timeout=2) as connection:
                await connection.fetchval("SELECT 1", timeout=2)
            dependencies["postgres"] = "healthy"
        except Exception:
            dependencies["postgres"] = "unreachable"
    healthy = all(value == "healthy" for value in dependencies.values())
    return JSONResponse({"status": "healthy" if healthy else "degraded", "service": SERVICE_NAME, "dependencies": dependencies}, status_code=200 if healthy else 503)


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(registry), media_type="text/plain; version=0.0.4")


@app.get("/api/users")
async def users(request: Request) -> dict[str, Any]:
    if SERVICE_KIND != "api":
        raise HTTPException(status_code=404, detail="Not available on payment service")
    started = time.monotonic()
    if not request.app.state.postgres:
        POSTGRES_QUERIES.labels(SERVICE_NAME, "error").inc()
        raise HTTPException(status_code=503, detail="PostgreSQL unavailable")
    try:
        async with request.app.state.postgres.acquire(timeout=2) as connection:
            rows = await connection.fetch("SELECT id, name, email FROM users ORDER BY id LIMIT 20", timeout=6)
            result = [dict(row) for row in rows]
    except Exception:
        POSTGRES_QUERIES.labels(SERVICE_NAME, "error").inc()
        raise
    duration = time.monotonic() - started
    POSTGRES_QUERIES.labels(SERVICE_NAME, "success").inc()
    POSTGRES_DURATION.labels(SERVICE_NAME).observe(duration)
    await ship_log("DEBUG", f"SELECT * FROM users took {duration * 1000:.0f}ms", query="SELECT * FROM users", duration_ms=round(duration * 1000, 2))
    return {"users": result}


@app.get("/api/products")
async def products(request: Request) -> dict[str, Any]:
    if SERVICE_KIND != "api":
        raise HTTPException(status_code=404, detail="Not available on payment service")
    try:
        result = await product_payload(request.app.state.redis)
        REDIS_CONNECTIONS.labels(SERVICE_NAME, "success").inc()
        REDIS_ACTIVE.labels(SERVICE_NAME).set(1)
    except Exception:
        REDIS_CONNECTIONS.labels(SERVICE_NAME, "error").inc()
        REDIS_ACTIVE.labels(SERVICE_NAME).set(0)
        raise
    return result


@app.post("/api/orders")
async def orders(request: Request) -> dict[str, str]:
    if SERVICE_KIND != "api":
        raise HTTPException(status_code=404, detail="Not available on payment service")
    order_id = uuid.uuid4().hex[:12]
    await request.app.state.redis.set(f"order:{order_id}", "created", ex=300)
    return {"order_id": order_id, "status": "created"}


@app.get("/api/slow-query")
async def slow_query(request: Request) -> dict[str, float]:
    if SERVICE_KIND != "api":
        raise HTTPException(status_code=404, detail="Not available on payment service")
    if not request.app.state.postgres:
        raise HTTPException(status_code=503, detail="PostgreSQL unavailable")
    started = time.monotonic()
    async with request.app.state.postgres.acquire() as connection:
        await connection.fetch("SELECT id FROM users ORDER BY id LIMIT 1", timeout=6)
    duration = time.monotonic() - started
    POSTGRES_DURATION.labels(SERVICE_NAME).observe(duration)
    return {"duration_seconds": duration}


@app.post("/api/payments")
async def create_payment(request: Request, payment: Payment) -> dict[str, Any]:
    if SERVICE_KIND != "payment":
        raise HTTPException(status_code=404, detail="Not available on API service")
    payment_id = uuid.uuid4().hex[:12]
    try:
        await request.app.state.redis.set(f"payment:{payment_id}", "processed", ex=300)
        REDIS_CONNECTIONS.labels(SERVICE_NAME, "success").inc()
    except Exception:
        REDIS_CONNECTIONS.labels(SERVICE_NAME, "error").inc()
        PAYMENTS_FAILED.labels(SERVICE_NAME).inc()
        raise
    PAYMENTS_PROCESSED.labels(SERVICE_NAME).inc()
    return {"payment_id": payment_id, "status": "processed", **payment.model_dump()}


@app.get("/api/payments/{payment_id}")
async def get_payment(request: Request, payment_id: str) -> dict[str, str]:
    if SERVICE_KIND != "payment":
        raise HTTPException(status_code=404, detail="Not available on API service")
    status = await request.app.state.redis.get(f"payment:{payment_id}")
    return {"payment_id": payment_id, "status": status or "unknown"}
