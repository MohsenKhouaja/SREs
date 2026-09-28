from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel

from .config import Settings
from .models import utc_iso


class LLMUnavailable(RuntimeError):
    """A model run failed; its audit can be persisted without inventing output."""

    def __init__(self, message: str, audit: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.audit = audit


_SENSITIVE_KEY = re.compile(r"api[_-]?key|authorization|password|secret|token", re.IGNORECASE)
_SENSITIVE_VALUE = re.compile(r"\b(?:gsk|sk)-[A-Za-z0-9_-]{8,}\b|Bearer\s+\S+", re.IGNORECASE)
_RETRY_AFTER = re.compile(r"try again in\s+([0-9.]+)s", re.IGNORECASE)
_MAX_AUDIT_TEXT = 64_000


def _sanitize(value: Any) -> Any:
    """Redact secrets and cap audit payloads before persistence."""
    if isinstance(value, dict):
        return {key: "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        redacted = _SENSITIVE_VALUE.sub("[REDACTED]", value)
        return redacted if len(redacted) <= _MAX_AUDIT_TEXT else redacted[:_MAX_AUDIT_TEXT] + "\n[TRUNCATED]"
    return value


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
    return str(content)


class GroqAgentRuntime:
    """Bounded Groq agent runner with structured output and auditable I/O."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.groq_api_key)

    def _model(self, max_tokens: int | None = None) -> ChatGroq:
        return ChatGroq(
            api_key=self.settings.groq_api_key,
            model=self.settings.groq_model,
            temperature=0,
            timeout=30,
            max_retries=0,
            max_tokens=max_tokens or self.settings.groq_max_tokens,
            reasoning_effort="low",
            service_tier=self.settings.groq_service_tier,
        )

    async def run(
        self,
        *,
        agent_name: str,
        system_prompt: str,
        user_prompt: str,
        tools: list[Any],
        response_schema: type[BaseModel],
        required_evidence_tools: set[str] | None = None,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        run_id = str(uuid.uuid4())
        started_at = utc_iso()
        started = time.monotonic()
        effective_system_prompt = system_prompt
        if tools:
            schema = json.dumps(response_schema.model_json_schema(), separators=(",", ":"))
            effective_system_prompt = (
                f"{system_prompt}\n\n"
                "After using the evidence tools, return only one JSON object matching this schema, with no Markdown fence: "
                f"{schema}. Do not call any tool except the provided evidence tools."
            )
        base_audit: dict[str, Any] = {
            "run_id": run_id,
            "agent": agent_name,
            "provider": "groq",
            "model": self.settings.groq_model,
            "input": _sanitize({"system_prompt": effective_system_prompt, "user_prompt": user_prompt}),
            "tool_calls": [],
            "started_at": started_at,
        }
        attempts = 0
        tool_calls: list[dict[str, Any]] = []
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        async def invoke(agent: Any, payload: dict[str, Any]) -> dict[str, Any]:
            nonlocal attempts
            for retry_index in range(12):
                attempts += 1
                try:
                    return await asyncio.wait_for(
                        agent.ainvoke(payload, config={"recursion_limit": 20}),
                        timeout=90,
                    )
                except Exception as exc:
                    message = str(exc)
                    rate_limited = "429" in message or "rate limit" in message.lower()
                    transient_network = "connection error" in message.lower() or "timed out" in message.lower()
                    if retry_index == 11 or not (rate_limited or transient_network):
                        raise
                    match = _RETRY_AFTER.search(message)
                    delay = float(match.group(1)) + 0.5 if match else min(2 ** retry_index, 10)
                    await asyncio.sleep(min(delay, 30))
            raise RuntimeError("Groq retry loop exhausted")

        try:
            if not self.enabled:
                raise LLMUnavailable("Groq is not configured. Set GROQ_API_KEY and retry.")
            model = self._model(max_tokens) if max_tokens else self._model()
            agent_options: dict[str, Any] = {"model": model, "tools": tools, "system_prompt": effective_system_prompt}
            if not tools:
                agent_options["response_format"] = response_schema
            agent = create_agent(**agent_options)
            result = await invoke(agent, {"messages": [{"role": "user", "content": user_prompt}]})
            pending: dict[str, dict[str, Any]] = {}
            final_text = ""
            for message in result.get("messages", []):
                if isinstance(message, AIMessage):
                    metadata = message.usage_metadata or {}
                    for key in usage:
                        usage[key] += int(metadata.get(key, 0) or 0)
                    for call in message.tool_calls:
                        record = {
                            "tool_call_id": call.get("id", ""),
                            "name": call.get("name", "unknown"),
                            "arguments": _sanitize(call.get("args", {})),
                            "result": None,
                            "status": "requested",
                        }
                        pending[record["tool_call_id"]] = record
                        tool_calls.append(record)
                    if not message.tool_calls and _text_content(message.content).strip():
                        final_text = _text_content(message.content).strip()
                elif isinstance(message, ToolMessage):
                    record = pending.get(message.tool_call_id)
                    if record is not None:
                        raw = _text_content(message.content)
                        try:
                            parsed: Any = json.loads(raw)
                        except (json.JSONDecodeError, TypeError):
                            parsed = raw
                        record["result"] = _sanitize(parsed)
                        record["status"] = "error" if message.status == "error" or (isinstance(parsed, dict) and parsed.get("status") == "error") else "completed"
            completed_evidence_tools = {
                call["name"]
                for call in tool_calls
                if call["status"] == "completed"
                and isinstance(call["result"], dict)
                and call["result"].get("status") == "success"
                and call["result"].get("data")
            }
            missing_tools = (required_evidence_tools or set()) - completed_evidence_tools
            if missing_tools:
                raise RuntimeError(f"No successful, non-empty observation was collected from required evidence tools: {sorted(missing_tools)}")
            structured = json.loads(final_text) if tools else result["structured_response"]
            output = response_schema.model_validate(structured).model_dump()
            return output, {
                **base_audit,
                "status": "completed",
                "attempts": attempts,
                "tool_calls": tool_calls,
                "output": _sanitize(output),
                "error": None,
                "completed_at": utc_iso(),
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "usage": usage,
            }
        except Exception as exc:
            safe_error = _sanitize(str(exc))
            audit = {
                **base_audit,
                "status": "failed",
                "attempts": attempts,
                "output": {},
                "tool_calls": tool_calls,
                "error": safe_error,
                "completed_at": utc_iso(),
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "usage": usage,
            }
            raise LLMUnavailable(f"Model analysis unavailable: {safe_error}", audit) from exc
