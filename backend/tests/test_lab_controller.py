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


def test_containerd_observation_uses_immutable_platform_manifest():
    container = FakeContainer(running=True)
    container.attrs['ImageManifestDescriptor'] = {'digest': 'sha256:platform-manifest'}
    observation = DockerOperations._observation(container)
    assert observation['image_id'] == 'sha256:platform-manifest'
    assert observation['image_config_id'] == 'sha256:redis'


def test_prepared_index_resolves_matching_platform_manifest():
    operations = docker_ops(FakeContainer())
    image = SimpleNamespace(id='sha256:index', attrs={
        'Os': 'linux', 'Architecture': 'amd64',
        'Descriptor': {'mediaType': 'application/vnd.oci.image.index.v1+json', 'digest': 'sha256:index'},
    })
    operations.client.images = SimpleNamespace(get=lambda reference: image)
    calls = []
    operations.client.api = SimpleNamespace(
        _url=lambda template, reference: template.format(reference),
        _get=lambda url, params: calls.append((url, params)) or 'response',
        _result=lambda response, json: {'Descriptor': {'digest': 'sha256:platform-manifest'}},
    )
    assert operations._image_id('prepared:v1') == 'sha256:platform-manifest'
    assert calls[0][1]['platform'] == '{"os": "linux", "architecture": "amd64"}'
    operations.client.api._result = lambda response, json: {'Descriptor': {'digest': 'sha256:index'}}
    with pytest.raises(RuntimeError, match='platform identity'):
        operations._image_id('prepared:v1')


def test_classic_prepared_image_keeps_config_digest():
    operations = docker_ops(FakeContainer())
    operations.client.images = SimpleNamespace(get=lambda reference: SimpleNamespace(id='sha256:classic', attrs={}))
    assert operations._image_id('prepared:v1') == 'sha256:classic'


@pytest.mark.parametrize("database", ["incident_db", "sres_production"])
async def test_database_termination_revalidates_pid_start_and_scope(monkeypatch, database):
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
    operations = PostgresOperations(SimpleNamespace(postgres_url="postgresql://lab", postgres_database=database))
    result = await operations.terminate_blocker(database, 42, start.isoformat())
    assert result["after"]["terminated"] is True
    with pytest.raises(StaleResource):
        await operations.terminate_blocker(database, 42, "2026-09-21T00:00:00+00:00")
    with pytest.raises(ValueError, match="allowlist"):
        await operations.terminate_blocker("unrelated_database", 42, start.isoformat())
