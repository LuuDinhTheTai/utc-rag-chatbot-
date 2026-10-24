from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    data_dir: str = 'data/local'
    admin_email: str = ''
    admin_password: str = ''
    google_api_key: str = ''
    gemini_model: str = 'gemini-2.5-flash'
    embedding_model: str = 'gemini-embedding-001'
    embedding_dimensions: int = Field(default=768, ge=1, le=3072)
    frontend_origin: str = 'http://localhost:3000'
    default_year: int = 2026
    question_routing_enabled: bool = True
    router_timeout_seconds: int = Field(default=20, ge=1, le=60)
    similarity_threshold: float = 0.65
    rate_limit_global: int = 120
    rate_limit_chat: int = 20
    rate_limit_login: int = 5
    rate_limit_admin_write: int = 30


@lru_cache
def settings():
    return Settings()
