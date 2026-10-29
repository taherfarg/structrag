"""Settings from the environment, plus the per-request retrieval knobs."""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql://postgres:postgres@127.0.0.1:55422/postgres"
    supabase_url: str = "http://127.0.0.1:55421"
    supabase_secret_key: SecretStr = SecretStr("")
    supabase_publishable_key: str = ""  # browser-safe; the backend only uses it in tests
    # Legacy HS256 projects only; new projects sign with asymmetric keys served via JWKS.
    supabase_jwt_secret: SecretStr | None = None
    storage_bucket: str = "documents"
    cors_origins: list[str] = ["http://localhost:5173"]

    # Any OpenAI-compatible endpoint. Embeddings may live elsewhere than chat.
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: SecretStr = Field(SecretStr(""), validation_alias=AliasChoices("LLM_API_KEY", "OPENROUTER_API_KEY"))
    embed_base_url: str | None = None
    embed_api_key: SecretStr | None = None
    llm_max_concurrency: int = 8
    llm_timeout_s: float = 120

    embedding_model: str = "openai/text-embedding-3-small"
    embedding_dim: int = 1536  # must match chunks.embedding in the migration
    router_model: str = "anthropic/claude-haiku-5.5"
    answer_model: str = "anthropic/claude-haiku-5.5"
    judge_model: str = "openai/gpt-5.6-luna"

    chunk_max_tokens: int = 350
    max_upload_mb: int = 50
    worker_enabled: bool = True
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


class RetrievalConfig(BaseModel):
    """Every knob that changes retrieval or answering. Stored verbatim with each benchmark run."""

    top_k: int = Field(8, ge=1, le=100)
    similarity: Literal["cosine", "inner_product", "l2"] = "cosine"
    context_token_budget: int = Field(3000, ge=200, le=60000)

    # structure routing
    routing_depth: int = Field(3, ge=1, le=6)
    toc_initial_depth: int = Field(2, ge=1, le=6)
    toc_token_budget: int = Field(4000, ge=300, le=60000)
    doc_select_max: int = Field(5, ge=1, le=100)
    max_selected_sections: int = Field(6, ge=1, le=50)
    include_parent_intro: bool = False
    structure_fallback: Literal["none", "vector"] = "none"

    # hybrid
    vector_candidates: int = Field(20, ge=1, le=200)
    rrf_k: int = Field(60, ge=1)
    weight_structure: float = Field(1.0, ge=0)
    weight_vector: float = Field(1.0, ge=0)
    rerank: Literal["none", "cross_encoder"] = "none"
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank_candidates: int = Field(30, ge=1, le=200)

    # answering
    router_model: str | None = None  # None = settings default
    answer_model: str | None = None
    judge_model: str | None = None
    answer_max_tokens: int = Field(1200, ge=64, le=8000)
    verify_citations: bool = False
