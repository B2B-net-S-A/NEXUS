from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "DynaMinds ATS"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Database (PostgreSQL)
    DATABASE_URL: str = "postgresql+asyncpg://dynaminds:dynaminds@localhost:5432/dynaminds"

    # Qdrant (vector store for semantic search)
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION: str = "candidates"

    # Voyage AI (embeddings)
    VOYAGE_API_KEY: str = ""
    VOYAGE_MODEL: str = "voyage-3"
    EMBEDDING_DIMENSION: int = 1024

    # Ollama (local LLM)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]

    # File uploads
    UPLOAD_DIR: str = "/tmp/dynaminds/uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
