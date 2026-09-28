from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING

from .models import utc_now


class Store(Protocol):
    async def health(self) -> str: ...
    async def initialize(self) -> None: ...
    async def close(self) -> None: ...
    async def create_investigation(self, document: dict[str, Any]) -> None: ...
    async def update_investigation(self, investigation_id: str, updates: dict[str, Any]) -> None: ...
    async def transition_investigation(self, investigation_id: str, expected_status: str, updates: dict[str, Any]) -> bool: ...
    async def get_investigation(self, investigation_id: str) -> dict[str, Any] | None: ...
    async def list_investigations(self) -> list[dict[str, Any]]: ...
    async def upsert_agent_state(self, investigation_id: str, agent_name: str, updates: dict[str, Any]) -> None: ...
    async def list_agent_states(self, investigation_id: str) -> list[dict[str, Any]]: ...
    async def create_approval(self, document: dict[str, Any]) -> None: ...
    async def update_approval(self, approval_id: str, updates: dict[str, Any]) -> None: ...
    async def decide_approval(self, approval_id: str, decision: str) -> bool: ...
    async def invalidate_pending_approvals(self, investigation_id: str, reason: str) -> None: ...
    async def get_approval(self, approval_id: str) -> dict[str, Any] | None: ...
    async def list_approvals(self, investigation_id: str | None = None) -> list[dict[str, Any]]: ...
    async def create_question(self, document: dict[str, Any]) -> None: ...
    async def list_questions(self, investigation_id: str) -> list[dict[str, Any]]: ...


def _serialize(document: dict[str, Any] | None) -> dict[str, Any] | None:
    if document is None:
        return None
    result = deepcopy(document)
    result.pop("_id", None)
    for key, value in list(result.items()):
        if isinstance(value, datetime):
            normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            result[key] = normalized.isoformat().replace("+00:00", "Z")
    return result


def approval_expired(document: dict[str, Any], now: datetime | None = None) -> bool:
    value = document.get("expires_at")
    if not value:
        return False
    deadline = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline <= (now or utc_now())


class InMemoryStore:
    async def health(self) -> str:
        return "in_memory"

    def __init__(self) -> None:
        self.investigations: dict[str, dict[str, Any]] = {}
        self.agent_states: dict[tuple[str, str], dict[str, Any]] = {}
        self.approvals: dict[str, dict[str, Any]] = {}
        self.questions: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def create_investigation(self, document: dict[str, Any]) -> None:
        async with self._lock:
            self.investigations[document["incident_id"]] = deepcopy(document)

    async def update_investigation(self, investigation_id: str, updates: dict[str, Any]) -> None:
        async with self._lock:
            self.investigations[investigation_id].update(deepcopy(updates))
            self.investigations[investigation_id]["updated_at"] = utc_now()

    async def get_investigation(self, investigation_id: str) -> dict[str, Any] | None:
        async with self._lock:
            return _serialize(self.investigations.get(investigation_id))

    async def transition_investigation(self, investigation_id: str, expected_status: str, updates: dict[str, Any]) -> bool:
        async with self._lock:
            document = self.investigations.get(investigation_id)
            if not document or document.get("status") != expected_status:
                return False
            document.update(deepcopy(updates))
            document["updated_at"] = utc_now()
            return True

    async def list_investigations(self) -> list[dict[str, Any]]:
        async with self._lock:
            docs = sorted(self.investigations.values(), key=lambda item: item["created_at"], reverse=True)
            return [_serialize(doc) for doc in docs if doc is not None]

    async def upsert_agent_state(self, investigation_id: str, agent_name: str, updates: dict[str, Any]) -> None:
        async with self._lock:
            key = (investigation_id, agent_name)
            base = self.agent_states.setdefault(key, {"investigation_id": investigation_id, "agent_name": agent_name})
            base.update(deepcopy(updates))

    async def list_agent_states(self, investigation_id: str) -> list[dict[str, Any]]:
        async with self._lock:
            docs = [doc for (inv_id, _), doc in self.agent_states.items() if inv_id == investigation_id]
            return [_serialize(doc) for doc in docs if doc is not None]

    async def create_approval(self, document: dict[str, Any]) -> None:
        async with self._lock:
            self.approvals[document["approval_id"]] = deepcopy(document)

    async def update_approval(self, approval_id: str, updates: dict[str, Any]) -> None:
        async with self._lock:
            self.approvals[approval_id].update(deepcopy(updates))

    async def decide_approval(self, approval_id: str, decision: str) -> bool:
        async with self._lock:
            document = self.approvals.get(approval_id)
            if not document or document.get("status") != "pending":
                return False
            if decision in {"approved", "rejected"} and approval_expired(document):
                return False
            if decision == "expired" and not approval_expired(document):
                return False
            document.update({"status": decision, "decided_at": utc_now()})
            return True

    async def invalidate_pending_approvals(self, investigation_id: str, reason: str) -> None:
        async with self._lock:
            for document in self.approvals.values():
                if document.get("investigation_id") == investigation_id and document.get("status") == "pending":
                    document.update({"status": "invalidated", "decided_at": utc_now(), "invalidation_reason": reason})

    async def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        async with self._lock:
            return _serialize(self.approvals.get(approval_id))

    async def list_approvals(self, investigation_id: str | None = None) -> list[dict[str, Any]]:
        async with self._lock:
            docs = list(self.approvals.values())
            if investigation_id:
                docs = [doc for doc in docs if doc["investigation_id"] == investigation_id]
            docs.sort(key=lambda item: item["created_at"], reverse=True)
            return [_serialize(doc) for doc in docs if doc is not None]

    async def create_question(self, document: dict[str, Any]) -> None:
        async with self._lock:
            self.questions[document["question_id"]] = deepcopy(document)

    async def list_questions(self, investigation_id: str) -> list[dict[str, Any]]:
        async with self._lock:
            docs = [doc for doc in self.questions.values() if doc["investigation_id"] == investigation_id]
            docs.sort(key=lambda item: item["created_at"])
            return [_serialize(doc) for doc in docs if doc is not None]


class MongoStore:
    async def health(self) -> str:
        try:
            await self.client.admin.command("ping")
            return "healthy"
        except Exception:
            return "unreachable"

    def __init__(self, url: str, database: str) -> None:
        self.client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=3000, tz_aware=True)
        self.db = self.client[database]

    async def initialize(self) -> None:
        await self.client.admin.command("ping")
        await self.db.investigations.create_index([("incident_id", ASCENDING)], unique=True)
        await self.db.investigations.create_index([("status", ASCENDING), ("created_at", DESCENDING)])
        await self.db.agent_states.create_index([("investigation_id", ASCENDING), ("agent_name", ASCENDING)], unique=True)
        await self.db.agent_states.create_index([("investigation_id", ASCENDING)])
        await self.db.approvals.create_index([("approval_id", ASCENDING)], unique=True)
        await self.db.approvals.create_index([("status", ASCENDING), ("investigation_id", ASCENDING)])
        await self.db.approvals.create_index([("investigation_id", ASCENDING)])
        await self.db.questions.create_index([("question_id", ASCENDING)], unique=True)
        await self.db.questions.create_index([("investigation_id", ASCENDING), ("created_at", ASCENDING)])

    async def close(self) -> None:
        self.client.close()

    async def create_investigation(self, document: dict[str, Any]) -> None:
        await self.db.investigations.insert_one(document)

    async def update_investigation(self, investigation_id: str, updates: dict[str, Any]) -> None:
        await self.db.investigations.update_one(
            {"incident_id": investigation_id}, {"$set": {**updates, "updated_at": utc_now()}}
        )

    async def get_investigation(self, investigation_id: str) -> dict[str, Any] | None:
        return _serialize(await self.db.investigations.find_one({"incident_id": investigation_id}))

    async def transition_investigation(self, investigation_id: str, expected_status: str, updates: dict[str, Any]) -> bool:
        result = await self.db.investigations.update_one(
            {"incident_id": investigation_id, "status": expected_status},
            {"$set": {**updates, "updated_at": utc_now()}},
        )
        return result.modified_count == 1

    async def list_investigations(self) -> list[dict[str, Any]]:
        cursor = self.db.investigations.find().sort("created_at", DESCENDING)
        return [_serialize(doc) async for doc in cursor]

    async def upsert_agent_state(self, investigation_id: str, agent_name: str, updates: dict[str, Any]) -> None:
        await self.db.agent_states.update_one(
            {"investigation_id": investigation_id, "agent_name": agent_name},
            {"$set": updates, "$setOnInsert": {"investigation_id": investigation_id, "agent_name": agent_name}},
            upsert=True,
        )

    async def list_agent_states(self, investigation_id: str) -> list[dict[str, Any]]:
        return [_serialize(doc) async for doc in self.db.agent_states.find({"investigation_id": investigation_id})]

    async def create_approval(self, document: dict[str, Any]) -> None:
        await self.db.approvals.update_one(
            {"approval_id": document["approval_id"]}, {"$setOnInsert": document}, upsert=True
        )

    async def update_approval(self, approval_id: str, updates: dict[str, Any]) -> None:
        await self.db.approvals.update_one({"approval_id": approval_id}, {"$set": updates})

    async def decide_approval(self, approval_id: str, decision: str) -> bool:
        now = utc_now()
        query: dict[str, Any] = {"approval_id": approval_id, "status": "pending"}
        # Older approvals store ISO strings; accept both representations without
        # weakening the deadline check inside the atomic pending-state claim.
        if decision in {"approved", "rejected", "expired"}:
            comparison = "$lte" if decision == "expired" else "$gt"
            query["$or"] = [
                {"expires_at": {comparison: now, "$type": "date"}},
                {"expires_at": {comparison: now.isoformat().replace("+00:00", "Z"), "$type": "string"}},
            ]
            if decision != "expired":
                query["$or"].extend([{"expires_at": {"$exists": False}}, {"expires_at": None}])
        result = await self.db.approvals.update_one(
            query,
            {"$set": {"status": decision, "decided_at": now}},
        )
        return result.modified_count == 1

    async def invalidate_pending_approvals(self, investigation_id: str, reason: str) -> None:
        await self.db.approvals.update_many(
            {"investigation_id": investigation_id, "status": "pending"},
            {"$set": {"status": "invalidated", "decided_at": utc_now(), "invalidation_reason": reason}},
        )

    async def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        return _serialize(await self.db.approvals.find_one({"approval_id": approval_id}))

    async def list_approvals(self, investigation_id: str | None = None) -> list[dict[str, Any]]:
        query = {"investigation_id": investigation_id} if investigation_id else {}
        cursor = self.db.approvals.find(query).sort("created_at", DESCENDING)
        return [_serialize(doc) async for doc in cursor]

    async def create_question(self, document: dict[str, Any]) -> None:
        await self.db.questions.insert_one(document)

    async def list_questions(self, investigation_id: str) -> list[dict[str, Any]]:
        cursor = self.db.questions.find({"investigation_id": investigation_id}).sort("created_at", ASCENDING)
        return [_serialize(doc) async for doc in cursor]
