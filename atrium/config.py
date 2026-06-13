from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Platform configuration, loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_prefix="ATRIUM_", env_file=".env", extra="ignore", populate_by_name=True
    )

    vault_path: Path = Path("vault")
    modules_path: Path = Path("modules")
    data_dir: Path = Path("data")
    host: str = "127.0.0.1"
    port: int = 8775

    # Context layer
    embeddings_provider: str = "fastembed"  # "fastembed" | "off"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    router_model: str = "claude-opus-4-8"
    llm_model: str = "claude-opus-4-8"      # default for ctx.llm; modules may override per call
    watch_vault: bool = True

    # Unprefixed on purpose (the SDK convention); read from env or .env. The app
    # exports it to the process env at startup so the anthropic SDK finds it.
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "atrium.db"


def get_settings() -> Settings:
    return Settings()
