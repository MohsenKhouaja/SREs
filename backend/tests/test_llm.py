from backend.app.config import Settings
from backend.app.llm import LLMClient


async def test_groq_completion_uses_configured_model_and_key(monkeypatch):
    request: dict = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"choices": [{"message": {"content": "  Groq result  "}}]}

    class FakeAsyncClient:
        def __init__(self, **kwargs) -> None:
            request["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def post(self, url: str, **kwargs):
            request.update(url=url, **kwargs)
            return FakeResponse()

    monkeypatch.setattr("backend.app.llm.httpx.AsyncClient", FakeAsyncClient)
    client = LLMClient(
        Settings(
            llm_provider="groq",
            groq_api_key="gsk-test",
            groq_model="llama-3.3-70b-versatile",
        )
    )

    assert client.enabled is True
    assert await client.complete("Refine this", "fallback") == "Groq result"
    assert request["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert request["headers"] == {"Authorization": "Bearer gsk-test"}
    assert request["json"] == {
        "model": "llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": "Refine this"}],
    }


async def test_groq_without_a_key_uses_fallback():
    client = LLMClient(Settings(llm_provider="groq"))

    assert client.enabled is False
    assert await client.complete("Refine this", "fallback") == "fallback"
