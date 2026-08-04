from __future__ import annotations

import httpx

from .config import Settings


class LLMClient:
    """Small provider switch used only to refine deterministic evidence synthesis."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return (self.settings.llm_provider == "openai" and bool(self.settings.openai_api_key)) or (
            self.settings.llm_provider == "gemini" and bool(self.settings.gemini_api_key)
        )

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
                response = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                    params={"key": self.settings.gemini_api_key},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                )
                response.raise_for_status()
                parts = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                return "".join(part.get("text", "") for part in parts).strip() or fallback
        except Exception:
            return fallback
