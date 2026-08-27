from __future__ import annotations

import logging

import httpx

from .config import Settings


logger = logging.getLogger("uvicorn.error")


class LLMClient:
    """Small provider switch used only to refine deterministic evidence synthesis."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        provider_keys = {
            "openai": self.settings.openai_api_key,
            "gemini": self.settings.gemini_api_key,
            "groq": self.settings.groq_api_key,
        }
        return bool(provider_keys.get(self.settings.llm_provider, ""))

    async def complete(self, prompt: str, fallback: str) -> str:
        if not self.enabled:
            return fallback
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if self.settings.llm_provider == "openai":
                    response = await client.post(
                        "https://api.openai.com/v1/responses",
                        headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                        json={"model": "gpt-5-mini", "input": prompt},
                    )
                    response.raise_for_status()
                    body = response.json()
                    return body.get("output_text", fallback).strip() or fallback
                if self.settings.llm_provider == "groq":
                    payload = {
                        "model": self.settings.groq_model,
                        "messages": [{"role": "user", "content": prompt}],
                    }
                    if self.settings.groq_model == "openai/gpt-oss-120b":
                        payload["reasoning_effort"] = self.settings.groq_reasoning_effort
                    response = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {self.settings.groq_api_key}"},
                        json=payload,
                    )
                    response.raise_for_status()
                    content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    if content.strip():
                        logger.info("llm_completion_success provider=groq model=%s", self.settings.groq_model)
                        return content.strip()
                    logger.warning("llm_completion_fallback provider=groq model=%s reason=empty_response", self.settings.groq_model)
                    return fallback
                response = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                    params={"key": self.settings.gemini_api_key},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                )
                response.raise_for_status()
                parts = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                return "".join(part.get("text", "") for part in parts).strip() or fallback
        except Exception as exc:
            if self.settings.llm_provider == "groq":
                logger.warning(
                    "llm_completion_fallback provider=groq model=%s error_type=%s",
                    self.settings.groq_model,
                    type(exc).__name__,
                )
            return fallback
