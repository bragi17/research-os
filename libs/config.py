"""Centralized configuration using pydantic-settings."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://ros_user:ros_pass@localhost:5432/research_os"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # LLM
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model_default: str = "gpt-4o"
    openai_model_cheap: str = "gpt-4o-mini"

    # Tongyi/DashScope Embedding & Rerank
    dashscope_api_key: str = ""
    dashscope_embedding_model: str = "text-embedding-v4"
    dashscope_embedding_dimension: int = 1024
    dashscope_multimodal_model: str = "qwen3-vl-embedding"
    dashscope_rerank_model: str = "gte-rerank-v2"

    # Academic APIs
    s2_api_key: str = ""
    openalex_email: str = ""
    crossref_email: str = ""
    unpaywall_email: str = ""

    # Storage
    storage_backend: str = "local"
    local_storage_dir: str = "/tmp/research-os-storage"
    minio_endpoint: str = "localhost:9000"

    # Auth
    jwt_secret: str = ""
    jwt_expiration_hours: int = 24
    auth_required: bool = False

    # GROBID
    grobid_url: str = "http://localhost:8070"

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:3001"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
