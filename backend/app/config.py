from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    supabase_url: str = ''
    supabase_secret_key: str = ''
    google_api_key: str = ''
    gemini_model: str = 'gemini-2.5-flash'
    embedding_model: str = 'gemini-embedding-001'
    frontend_origin: str = 'http://localhost:3000'
    default_year: int = 2026
    similarity_threshold: float = 0.65


@lru_cache
def settings():
    return Settings()
