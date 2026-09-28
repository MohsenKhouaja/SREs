from langchain_core.messages import AIMessage, ToolMessage
import pytest

from backend.app.config import Settings
from backend.app.llm import GroqAgentRuntime, LLMUnavailable, _sanitize
from backend.app.models import AgentFindingOutput
from backend.app.tools import query_loki


async def test_groq_agent_records_structured_output_tools_and_usage(monkeypatch):
    captured: dict = {"create": [], "invoke": []}

    class FakeAgent:
        async def ainvoke(self, payload, config):
            captured["invoke"].append({"payload": payload, "config": config})
            return {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[{"id": "call-1", "name": "query_loki", "args": {"query": "errors"}}],
                        usage_metadata={"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
                    ),
                    ToolMessage(content='{"status":"success"}', tool_call_id="call-1"),
                    AIMessage(content='{"finding":"Groq finding","insufficient_evidence":false}', usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}),
                ],
            }

    def fake_create_agent(**kwargs):
        captured["create"].append(kwargs)
        return FakeAgent()

    runtime = GroqAgentRuntime(Settings(groq_api_key="gsk-test-secret", groq_model="openai/gpt-oss-120b"))
    monkeypatch.setattr(runtime, "_model", lambda: object())
    monkeypatch.setattr("backend.app.llm.create_agent", fake_create_agent)

    output, audit = await runtime.run(
        agent_name="log",
        system_prompt="Inspect logs",
        user_prompt="Find the failure",
        tools=[query_loki],
        response_schema=AgentFindingOutput,
    )

    assert output == {"finding": "Groq finding", "insufficient_evidence": False}
    assert audit["status"] == "completed"
    assert audit["provider"] == "groq" and audit["model"] == "openai/gpt-oss-120b"
    assert audit["tool_calls"][0]["result"] == {"status": "success"}
    assert audit["usage"]["total_tokens"] == 19
    assert all(item["config"] == {"recursion_limit": 20} for item in captured["invoke"])
    assert len(captured["create"]) == 1
    assert captured["create"][0]["tools"] == [query_loki]
    assert "response_format" not in captured["create"][0]


async def test_missing_groq_key_fails_without_generating_findings():
    runtime = GroqAgentRuntime(Settings(groq_api_key=""))

    with pytest.raises(LLMUnavailable) as caught:
        await runtime.run(agent_name="metrics", system_prompt="Inspect metrics", user_prompt="Find the failure", tools=[], response_schema=AgentFindingOutput)
    audit = caught.value.audit
    assert audit["output"] == {}
    assert audit["status"] == "failed"
    assert audit["attempts"] == 0
    assert "not configured" in audit["error"]


async def test_groq_agent_retries_provider_rate_limit(monkeypatch):
    calls = 0

    class FakeAgent:
        async def ainvoke(self, payload, config):
            nonlocal calls
            calls += 1
            if calls < 10:
                raise RuntimeError("Error code: 429 - Rate limit reached. Please try again in 0.01s")
            return {
                "structured_response": AgentFindingOutput(finding="Recovered after retry", insufficient_evidence=False),
                "messages": [],
            }

    runtime = GroqAgentRuntime(Settings(groq_api_key="gsk-test-secret"))
    monkeypatch.setattr(runtime, "_model", lambda: object())
    monkeypatch.setattr("backend.app.llm.create_agent", lambda **kwargs: FakeAgent())

    output, audit = await runtime.run(
        agent_name="retry-proof",
        system_prompt="Return a finding",
        user_prompt="Retry safely",
        tools=[],
        response_schema=AgentFindingOutput,
    )

    assert output == {"finding": "Recovered after retry", "insufficient_evidence": False}
    assert audit["status"] == "completed"
    assert audit["attempts"] == 10


def test_audit_sanitizer_redacts_keys_and_bearer_values():
    value = _sanitize({"api_key": "gsk-secret-value", "message": "Authorization: Bearer abc123"})
    assert value["api_key"] == "[REDACTED]"
    assert "abc123" not in value["message"]


async def test_run_can_raise_the_output_limit_for_a_larger_structured_schema(monkeypatch):
    captured = []

    class Agent:
        async def ainvoke(self, payload, config):
            return {
                "structured_response": AgentFindingOutput(finding="Bounded response", insufficient_evidence=False),
                "messages": [],
            }

    runtime = GroqAgentRuntime(Settings(groq_api_key="test", groq_max_tokens=1024))
    monkeypatch.setattr(runtime, "_model", lambda max_tokens=None: captured.append(max_tokens) or object())
    monkeypatch.setattr("backend.app.llm.create_agent", lambda **kwargs: Agent())
    await runtime.run(
        agent_name="correlation",
        system_prompt="Correlate",
        user_prompt="Use evidence",
        tools=[],
        response_schema=AgentFindingOutput,
        max_tokens=1536,
    )
    assert captured == [1536]


@pytest.mark.parametrize("result", [{"status": "error", "data": [], "metadata": {"error": "offline"}}, {"status": "success", "data": []}])
async def test_failed_or_empty_tool_response_cannot_count_as_evidence(monkeypatch, result):
    import json
    class Agent:
        async def ainvoke(self, payload, config):
            return {"messages": [AIMessage(content="", tool_calls=[{"id": "q", "name": "query_loki", "args": {}}]), ToolMessage(content=json.dumps(result), tool_call_id="q")]}
    runtime = GroqAgentRuntime(Settings(groq_api_key="test"))
    monkeypatch.setattr(runtime, "_model", lambda: object())
    monkeypatch.setattr("backend.app.llm.create_agent", lambda **kwargs: Agent())
    with pytest.raises(LLMUnavailable, match="No successful") as caught:
        await runtime.run(agent_name="log", system_prompt="Inspect", user_prompt="Observe", tools=[query_loki], response_schema=AgentFindingOutput, required_evidence_tools={"query_loki"})
    assert caught.value.audit["output"] == {}
    assert caught.value.audit["tool_calls"][0]["result"] == result
