from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_max_tokens: int = 1024
    groq_service_tier: str = "on_demand"
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_database: str = "incident_response"
    prometheus_url: str = "http://localhost:9090"
    loki_url: str = "http://localhost:3100"
    sample_api_url: str = "http://localhost:8001"
    sample_payment_url: str = "http://localhost:8002"
    lab_controller_url: str = "http://127.0.0.1:8010"
    lab_monitor_token: str = ""
    lab_operator_token: str = ""
    investigation_warmup_seconds: float = 10
    verification_rounds: int = 3
    verification_interval_seconds: float = 5
    verification_timeout_seconds: float = 60
    use_in_memory_store: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
