from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "FinDoc Verifier Agent"
    artifact_root: Path = Path("runs")
    task_store_path: Path | None = None
    mineru_endpoint: str | None = None
    mineru_cli: str = "mineru"
    mineru_max_concurrency: int = 1
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
