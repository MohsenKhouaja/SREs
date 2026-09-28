import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


CONTROLLER_ROOT = Path(__file__).parents[2] / "lab-controller"
sys.path.insert(0, str(CONTROLLER_ROOT))

from app.docker_ops import DockerOperations, StaleResource  # noqa: E402
from app.postgres_ops import PostgresOperations  # noqa: E402


class FakeContainer:
    def __init__(self, container_id="redis-id", running=False):
        self.id = container_id
        self.name = "sres-redis-1"
        self.status = "running" if running else "exited"
        self.image = SimpleNamespace(tags=["redis:7-alpine"])
        self.attrs = {
            "Image": "sha256:redis",
            "Config": {"Image": "redis:7-alpine", "Labels": {"com.docker.compose.service": "redis"}, "Env": ["SECRET=not-public"]},
            "State": {"Status": self.status, "Running": running, "StartedAt": "start", "FinishedAt": "finish"},
        }

    def reload(self):
        return None

    def start(self):
        self.status = "running"
        self.attrs["State"].update({"Status": "running", "Running": True})


def docker_ops(container):
    operations = DockerOperations.__new__(DockerOperations)
    operations.settings = SimpleNamespace(redis_service="redis", sample_api_service="sample-api", compose_project="sres", sample_api_network="sres_incident-response-net")
    operations.client = SimpleNamespace(containers=SimpleNamespace(list=lambda **kwargs: [container]))
    return operations


async def test_resource_observation_is_allowlisted_and_redacts_container_environment():
    operations = docker_ops(FakeContainer())
    observation = await operations.inspect("redis")
    assert observation["container_id"] == "redis-id"
    assert observation["image_tags"] == ["redis:7-alpine"]
    assert "Env" not in observation
    with pytest.raises(ValueError, match="allowlist"):
        await operations.inspect("mongodb")


async def test_start_service_rejects_stale_container_identity():
    operations = docker_ops(FakeContainer())
    with pytest.raises(StaleResource, match="identity changed"):
        await operations.start_service("redis", "old-id")


def test_release_swap_validates_network_before_stopping_current_container():
    container = FakeContainer(container_id="api-id", running=True)
    operations = docker_ops(container)
    operations._image_id = lambda _image: "sha256:v2"
    operations.client.networks = SimpleNamespace(get=lambda _name: (_ for _ in ()).throw(RuntimeError("network missing")))
    with pytest.raises(RuntimeError, match="network missing"):
        operations._replace_sample_api("api-id", "sres-sample-api:v2")
    assert container.status == "running"


async def test_database_termination_revalidates_pid_start_and_scope(monkeypatch):
    start = datetime(2026, 9, 22, tzinfo=timezone.utc)

    class Connection:
        async def fetchrow(self, query, pid):
            return {"pid": pid, "backend_start": start, "application_name": "sres-lab-blocker:run", "holds_users_lock": True}

        async def fetchval(self, query, pid):
            return True

        async def close(self):
            return None

    async def connect(*args, **kwargs):
        return Connection()

    monkeypatch.setattr("app.postgres_ops.asyncpg.connect", connect)
    operations = PostgresOperations(SimpleNamespace(postgres_url="postgresql://lab"))
    result = await operations.terminate_blocker("incident_db", 42, start.isoformat())
    assert result["after"]["terminated"] is True
    with pytest.raises(StaleResource):
        await operations.terminate_blocker("incident_db", 42, "2026-09-21T00:00:00+00:00")
