from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import docker
from docker.errors import ImageNotFound, NotFound

from .config import Settings


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class DockerOperations:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = docker.from_env()

    def _container(self, service: str):
        if service not in {self.settings.redis_service, self.settings.sample_api_service}:
            raise ValueError("Resource is outside the lab allowlist")
        matches = self.client.containers.list(
            all=True,
            filters={
                "label": [
                    f"com.docker.compose.project={self.settings.compose_project}",
                    f"com.docker.compose.service={service}",
                ]
            },
        )
        if len(matches) != 1:
            raise LookupError(f"Expected one {service} container in project {self.settings.compose_project}; found {len(matches)}")
        return matches[0]

    @staticmethod
    def _observation(container: Any) -> dict[str, Any]:
        container.reload()
        attrs = container.attrs
        state = attrs.get("State", {})
        image_config = attrs.get("Image", "")
        image = (attrs.get("ImageManifestDescriptor") or {}).get("digest") or image_config
        configured_image = attrs.get("Config", {}).get("Image")
        return {
            "observation_id": f"container:{container.id}:{state.get('StartedAt') or state.get('FinishedAt')}",
            "resource_id": attrs.get("Config", {}).get("Labels", {}).get("com.docker.compose.service", "unknown"),
            "container_id": container.id,
            "name": container.name,
            "state": state.get("Status", container.status),
            "running": bool(state.get("Running")),
            "health": state.get("Health", {}).get("Status"),
            "image_id": image,
            "image_config_id": image_config,
            # Container.image performs a second image lookup, which fails for a
            # still-running container after its tag has been rebuilt. The
            # configured reference is part of the immutable container record.
            "image_tags": [configured_image] if configured_image else [],
            "started_at": state.get("StartedAt"),
            "finished_at": state.get("FinishedAt"),
            "observed_at": utc_iso(),
        }

    async def inspect(self, service: str) -> dict[str, Any]:
        return await asyncio.to_thread(lambda: self._observation(self._container(service)))

    async def stop_redis(self) -> dict[str, Any]:
        def stop() -> dict[str, Any]:
            container = self._container(self.settings.redis_service)
            before = self._observation(container)
            if before["running"]:
                container.stop(timeout=10)
            after = self._observation(container)
            if after["running"]:
                raise RuntimeError("Redis container remained running")
            return {"before": before, "after": after}

        return await asyncio.to_thread(stop)

    async def start_service(self, resource_id: str, expected_container_id: str) -> dict[str, Any]:
        def start() -> dict[str, Any]:
            container = self._container(resource_id)
            before = self._observation(container)
            if before["container_id"] != expected_container_id:
                raise StaleResource("Container identity changed after approval")
            if before["running"]:
                raise StaleResource("Container is no longer stopped")
            container.start()
            container.reload()
            after = self._observation(container)
            if not after["running"]:
                raise RuntimeError("Container did not enter running state")
            return {"before": before, "after": after}

        return await asyncio.to_thread(start)

    def _image_id(self, reference: str) -> str:
        try:
            image = self.client.images.get(reference)
            descriptor = image.attrs.get("Descriptor") or {}
            if descriptor.get("mediaType") in {
                "application/vnd.oci.image.index.v1+json",
                "application/vnd.docker.distribution.manifest.list.v2+json",
            }:
                # Resolve the same platform manifest recorded on Docker 29 containers.
                response = self.client.api._get(
                    self.client.api._url("/images/{0}/json", reference),
                    params={"platform": json.dumps({"os": image.attrs["Os"], "architecture": image.attrs["Architecture"]})},
                )
                resolved = self.client.api._result(response, json=True)
                digest = (resolved.get("Descriptor") or {}).get("digest")
                if not digest or digest == descriptor.get("digest"):
                    raise RuntimeError("Prepared image platform identity could not be resolved")
                return digest
            return image.id
        except ImageNotFound as exc:
            raise RuntimeError(f"Required prepared image is unavailable: {reference}") from exc

    async def image_ids(self) -> dict[str, str]:
        return await asyncio.to_thread(
            lambda: {
                "v1": self._image_id(self.settings.sample_api_v1_image),
                "v2": self._image_id(self.settings.sample_api_v2_image),
            }
        )

    def _replace_sample_api(self, expected_container_id: str, image: str) -> dict[str, Any]:
        current = self._container(self.settings.sample_api_service)
        before = self._observation(current)
        if before["container_id"] != expected_container_id:
            raise StaleResource("Sample API container identity changed after approval")
        if not before["running"]:
            raise StaleResource("Sample API is no longer running")
        target_image_id = self._image_id(image)
        if before["image_id"] == target_image_id:
            raise StaleResource("Requested image is already running")
        network = self.client.networks.get(self.settings.sample_api_network)
        name = current.name
        current.stop(timeout=10)
        backup_name = f"{name}-previous-{current.id[:8]}"
        current.rename(backup_name)
        created = None
        try:
            created = self.client.containers.create(
                image,
                name=name,
                command=["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port 8001"],
                environment={
                    "SERVICE_KIND": "api",
                    "PORT": "8001",
                    "REDIS_URL": self.settings.sample_api_redis_url,
                    "POSTGRES_URL": self.settings.sample_api_postgres_url,
                    "LOKI_URL": self.settings.sample_api_loki_url,
                },
                labels={
                    "com.docker.compose.project": self.settings.compose_project,
                    "com.docker.compose.service": self.settings.sample_api_service,
                    "com.docker.compose.container-number": "1",
                    "com.docker.compose.oneoff": "False",
                    "sres.lab.managed": "true",
                },
                ports={"8001/tcp": ("127.0.0.1", self.settings.sample_api_port)} if self.settings.sample_api_publish_port else None,
                healthcheck={
                    "test": ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8001/live', timeout=3)"],
                    "interval": 10_000_000_000,
                    "timeout": 5_000_000_000,
                    "retries": 5,
                    "start_period": 20_000_000_000,
                },
            )
            network.connect(created, aliases=[self.settings.sample_api_service])
            created.start()
            after = self._observation(created)
        except Exception:
            if created is not None:
                created.remove(force=True)
            current.rename(name)
            current.start()
            raise
        current.remove()
        return {"before": before, "after": after}

    async def deploy_regression(self) -> dict[str, Any]:
        current = await self.inspect(self.settings.sample_api_service)
        ids = await self.image_ids()
        if current["image_id"] != ids["v1"]:
            raise StaleResource("Release regression requires the prepared v1 baseline")
        return await asyncio.to_thread(
            self._replace_sample_api,
            current["container_id"],
            self.settings.sample_api_v2_image,
        )

    async def rollback_release(
        self,
        resource_id: str,
        expected_container_id: str,
        expected_current_image_id: str,
        previous_image_id: str,
    ) -> dict[str, Any]:
        if resource_id != self.settings.sample_api_service:
            raise ValueError("Only sample-api release rollback is allowed")
        ids = await self.image_ids()
        if previous_image_id != ids["v1"]:
            raise ValueError("Previous image is not the prepared v1 image")
        current = await self.inspect(resource_id)
        if current["image_id"] != expected_current_image_id:
            raise StaleResource("Current image changed after approval")
        return await asyncio.to_thread(self._replace_sample_api, expected_container_id, self.settings.sample_api_v1_image)


class StaleResource(RuntimeError):
    pass
