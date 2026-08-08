from __future__ import annotations

import asyncio
import json
import os
import random
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest


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


class Toggle(BaseModel):
    enabled: bool


class Deployment(BaseModel):
    version: str


class Payment(BaseModel):
    amount: float
    currency: str = "USD"


class SimulationState:
    redis_failure = False
    slow_db = False
    version = "v1"


state = SimulationState()


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
            await client.post(f"{LOKI_URL}/loki/api/v1/push", json=body)
    except httpx.HTTPError:
        pass


async def synthetic_traffic() -> None:
    while True:
        try:
            if state.redis_failure:
                REDIS_ACTIVE.labels(SERVICE_NAME).set(0)
                REDIS_CONNECTIONS.labels(SERVICE_NAME, "error").inc()
                HTTP_REQUESTS.labels(SERVICE_NAME, "synthetic", "GET", "500").inc(8)
                await ship_log("ERROR", "Redis connection timeout; connection pool unavailable", status=500, duration_ms=900)
            elif state.slow_db and SERVICE_KIND == "api":
                POSTGRES_QUERIES.labels(SERVICE_NAME, "slow").inc()
                POSTGRES_DURATION.labels(SERVICE_NAME).observe(8)
                HTTP_DURATION.labels(SERVICE_NAME, "/api/users").observe(8)
                await ship_log("DEBUG", "SELECT * FROM users took 8000ms", query="SELECT * FROM users", duration_ms=8000)
            elif state.version == "v2":
                HTTP_REQUESTS.labels(SERVICE_NAME, "synthetic", "GET", "500").inc(8)
                await ship_log("ERROR", "Internal server error introduced by deployment v2", version="v2", status=500)
            else:
                REDIS_ACTIVE.labels(SERVICE_NAME).set(1)
                HTTP_REQUESTS.labels(SERVICE_NAME, "synthetic", "GET", "200").inc(5)
                HTTP_DURATION.labels(SERVICE_NAME, "synthetic").observe(random.uniform(0.02, 0.1))
                await ship_log("INFO", "Synthetic request completed", status=200, duration_ms=random.randint(20, 100), version="v1")
        except Exception:
            pass
        await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        app.state.postgres = await asyncpg.create_pool(POSTGRES_URL, min_size=1, max_size=3)
    except Exception:
        app.state.postgres = None
    task = asyncio.create_task(synthetic_traffic())
    yield
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await app.state.redis.aclose()
    if app.state.postgres:
        await app.state.postgres.close()


app = FastAPI(title=f"Wayfinder sample {SERVICE_NAME}", lifespan=lifespan)


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    if request.url.path in {"/metrics", "/health"}:
        return await call_next(request)
    started = time.monotonic()
    if state.version == "v2" and request.url.path.startswith("/api/") and "/simulate/" not in request.url.path:
        response = Response(content='{"detail":"Internal server error"}', status_code=500, media_type="application/json")
    else:
        response = await call_next(request)
    duration = time.monotonic() - started
    HTTP_REQUESTS.labels(SERVICE_NAME, request.url.path, request.method, str(response.status_code)).inc()
    HTTP_DURATION.labels(SERVICE_NAME, request.url.path).observe(duration)
    level = "ERROR" if response.status_code >= 500 else "INFO"
    await ship_log(level, f"{request.method} {request.url.path} {response.status_code} {duration * 1000:.0f}ms", method=request.method, path=request.url.path, status=response.status_code, duration_ms=round(duration * 1000, 2), version=state.version)
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": SERVICE_NAME, "version": state.version}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(registry), media_type="text/plain; version=0.0.4")


@app.get("/api/users")
async def users(request: Request) -> dict[str, Any]:
    if SERVICE_KIND != "api":
        raise HTTPException(status_code=404, detail="Not available on payment service")
    delay = 8 if state.slow_db else 0
    started = time.monotonic()
    if delay:
        await asyncio.sleep(delay)
    if request.app.state.postgres:
        async with request.app.state.postgres.acquire() as connection:
            rows = await connection.fetch("SELECT id, name, email FROM users ORDER BY id LIMIT 20")
            result = [dict(row) for row in rows]
    else:
        result = [{"id": 1, "name": "Ada", "email": "ada@example.test"}]
    duration = time.monotonic() - started
    POSTGRES_QUERIES.labels(SERVICE_NAME, "success").inc()
    POSTGRES_DURATION.labels(SERVICE_NAME).observe(duration)
    await ship_log("DEBUG", f"SELECT * FROM users took {duration * 1000:.0f}ms", query="SELECT * FROM users", duration_ms=round(duration * 1000, 2))
    return {"users": result}


@app.get("/api/products")
async def products(request: Request) -> dict[str, Any]:
    if SERVICE_KIND != "api":
        raise HTTPException(status_code=404, detail="Not available on payment service")
    if state.redis_failure:
        REDIS_ACTIVE.labels(SERVICE_NAME).set(0)
        REDIS_CONNECTIONS.labels(SERVICE_NAME, "error").inc()
        raise HTTPException(status_code=503, detail="Redis connection refused")
    REDIS_CONNECTIONS.labels(SERVICE_NAME, "success").inc()
    REDIS_ACTIVE.labels(SERVICE_NAME).set(1)
    await request.app.state.redis.set("products:last-read", str(time.time()), ex=60)
    return {"products": [{"id": 1, "name": "Telemetry adapter"}]}


@app.post("/api/orders")
async def orders(request: Request) -> dict[str, str]:
    if SERVICE_KIND != "api":
        raise HTTPException(status_code=404, detail="Not available on payment service")
    if state.redis_failure:
        raise HTTPException(status_code=503, detail="Redis connection refused")
    order_id = uuid.uuid4().hex[:12]
    await request.app.state.redis.set(f"order:{order_id}", "created", ex=300)
    return {"order_id": order_id, "status": "created"}


@app.get("/api/slow-query")
async def slow_query(request: Request) -> dict[str, float]:
    if SERVICE_KIND != "api":
        raise HTTPException(status_code=404, detail="Not available on payment service")
    started = time.monotonic()
    await asyncio.sleep(8 if state.slow_db else 0.05)
    duration = time.monotonic() - started
    POSTGRES_DURATION.labels(SERVICE_NAME).observe(duration)
    return {"duration_seconds": duration}


@app.post("/api/payments")
async def create_payment(request: Request, payment: Payment) -> dict[str, Any]:
    if SERVICE_KIND != "payment":
        raise HTTPException(status_code=404, detail="Not available on API service")
    if state.redis_failure:
        PAYMENTS_FAILED.labels(SERVICE_NAME).inc()
        raise HTTPException(status_code=503, detail="Redis connection refused")
    payment_id = uuid.uuid4().hex[:12]
    await request.app.state.redis.set(f"payment:{payment_id}", "processed", ex=300)
    PAYMENTS_PROCESSED.labels(SERVICE_NAME).inc()
    return {"payment_id": payment_id, "status": "processed", **payment.model_dump()}


@app.get("/api/payments/{payment_id}")
async def get_payment(request: Request, payment_id: str) -> dict[str, str]:
    if SERVICE_KIND != "payment":
        raise HTTPException(status_code=404, detail="Not available on API service")
    status = await request.app.state.redis.get(f"payment:{payment_id}")
    return {"payment_id": payment_id, "status": status or "unknown"}


@app.post("/api/simulate/redis-failure")
async def simulate_redis(body: Toggle) -> dict[str, Any]:
    state.redis_failure = body.enabled
    await ship_log("WARNING" if body.enabled else "INFO", f"Redis failure simulation {'enabled' if body.enabled else 'disabled'}")
    return {"scenario": "redis-failure", "enabled": state.redis_failure}


@app.post("/api/simulate/slow-db")
async def simulate_slow_db(body: Toggle) -> dict[str, Any]:
    if SERVICE_KIND != "api":
        raise HTTPException(status_code=404, detail="Not available on payment service")
    state.slow_db = body.enabled
    await ship_log("WARNING" if body.enabled else "INFO", f"Slow database simulation {'enabled' if body.enabled else 'disabled'}")
    return {"scenario": "slow-db", "enabled": state.slow_db}


@app.post("/api/simulate/bad-deployment")
async def simulate_deployment(body: Deployment) -> dict[str, str]:
    if body.version not in {"v1", "v2"}:
        raise HTTPException(status_code=400, detail="version must be v1 or v2")
    state.version = body.version
    await ship_log("WARNING" if body.version == "v2" else "INFO", f"Deployment switched to {body.version}", version=body.version)
    return {"scenario": "bad-deployment", "version": state.version}
