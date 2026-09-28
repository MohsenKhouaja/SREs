from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mongodb_url: str = "mongodb://127.0.0.1:27017"
    mongodb_database: str = "sres_lab_control"
    monitor_token: str
    operator_token: str
    compose_project: str = "sres"
    redis_service: str = "redis"
    sample_api_service: str = "sample-api"
    sample_api_port: int = 8001
    sample_api_network: str = "incident-response-net"
    sample_api_v1_image: str = "sres-sample-api:v1"
    sample_api_v2_image: str = "sres-sample-api:v2"
    postgres_url: str = "postgresql://lab_controller:lab_controller@127.0.0.1:5432/incident_db"
    sample_api_redis_url: str = "redis://redis:6379"
    sample_api_postgres_url: str = "postgresql://app_user:app_user@postgres:5432/incident_db"
    sample_api_loki_url: str = "http://loki:3100"
    maximum_run_seconds: int = 900


@lru_cache
def get_settings() -> Settings:
    return Settings()
