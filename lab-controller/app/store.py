from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def serialize(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if document is None:
        return None
    result = {key: value for key, value in document.items() if key != "_id"}
    for key, value in list(result.items()):
        if isinstance(value, datetime):
            normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            result[key] = normalized.isoformat().replace("+00:00", "Z")
    return result


class ControlStore:
    def __init__(self, url: str, database: str) -> None:
        self.client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=3000, tz_aware=True)
        self.db = self.client[database]

    async def initialize(self) -> None:
        await self.client.admin.command("ping")
        await self.db.runs.create_index([("run_id", ASCENDING)], unique=True)
        await self.db.runs.create_index([("status", ASCENDING)])
        await self.db.operations.create_index([("action_id", ASCENDING)], unique=True)
        await self.db.releases.create_index([("service", ASCENDING), ("observed_at", ASCENDING)])
        await self.db.leases.create_index([("lease", ASCENDING)], unique=True)

    def close(self) -> None:
        self.client.close()

    async def acquire_lease(self, run_id: str, expires_at: datetime) -> bool:
        now = utc_now()
        result = await self.db.leases.find_one_and_update(
            {"lease": "shared-lab", "$or": [{"run_id": run_id}, {"expires_at": {"$lte": now}}]},
            {"$set": {"run_id": run_id, "expires_at": expires_at, "updated_at": now}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return bool(result and result.get("run_id") == run_id)

    async def release_lease(self, run_id: str) -> None:
        await self.db.leases.delete_one({"lease": "shared-lab", "run_id": run_id})

    async def create_run(self, document: dict[str, Any]) -> None:
        await self.db.runs.insert_one(document)

    async def update_run(self, run_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        document = await self.db.runs.find_one_and_update(
            {"run_id": run_id},
            {"$set": {**updates, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return serialize(document)

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        return serialize(await self.db.runs.find_one({"run_id": run_id}))

    async def get_operation(self, action_id: str) -> dict[str, Any] | None:
        return serialize(await self.db.operations.find_one({"action_id": action_id}))

    async def begin_operation(self, document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        existing = await self.db.operations.find_one({"action_id": document["action_id"]})
        if existing:
            return serialize(existing), False
        try:
            await self.db.operations.insert_one(document)
        except DuplicateKeyError:
            existing = await self.db.operations.find_one({"action_id": document["action_id"]})
            return serialize(existing), False
        return serialize(document), True

    async def update_operation(self, action_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        document = await self.db.operations.find_one_and_update(
            {"action_id": action_id},
            {"$set": {**updates, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return serialize(document)

    async def add_release(self, document: dict[str, Any]) -> None:
        await self.db.releases.insert_one(document)

    async def releases(self, service: str) -> list[dict[str, Any]]:
        cursor = self.db.releases.find({"service": service}).sort("observed_at", DESCENDING).limit(10)
        return [serialize(document) async for document in cursor]
