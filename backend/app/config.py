from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"
    llm_provider: str = "deterministic"
    openai_api_key: str = ""
    gemini_api_key: str = ""
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_database: str = "incident_response"
    prometheus_url: str = "http://localhost:9090"
    loki_url: str = "http://localhost:3100"
    sample_api_url: str = "http://localhost:8001"
    sample_payment_url: str = "http://localhost:8002"
    simulation_warmup_seconds: float = 10
    use_in_memory_store: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
