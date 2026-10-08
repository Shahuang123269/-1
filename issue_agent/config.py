from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IA_", env_file=".env", extra="ignore")
    model_mode: Literal["fixture", "deepseek"] = "fixture"
    tool_mode: Literal["fixture", "github"] = "fixture"
    repository: str = "Shahuang123269/-1"
    data_dir: Path = Path("data")
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    github_token: SecretStr = SecretStr("")
    api_token: SecretStr = SecretStr("")
    allow_remote_writes: bool = False
    github_read_token: SecretStr = SecretStr("")
    webhook_secret: SecretStr = SecretStr("")
    policy_path: Path | None = None
    embedded_worker: bool = True
    queue_limit: int = Field(64, ge=1, le=1000)
    worker_poll_seconds: float = Field(0.2, ge=0.02, le=10)
    max_model_calls: int = Field(6, ge=2, le=20)
    max_tool_calls: int = Field(10, ge=1, le=40)
    max_context_chars: int = Field(40000, ge=2000, le=200000)
    timeout_seconds: float = Field(30, gt=0, le=120)
    http_trust_env: bool = True

    @field_validator("repository")
    @classmethod
    def valid_repo(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
            raise ValueError("repository 必须是 owner/name")
        return value
