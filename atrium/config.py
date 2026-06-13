from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Platform configuration, loaded from environment / .env."""

    model_config = SettingsConfigDict(env_prefix="ATRIUM_", env_file=".env", extra="ignore")

    vault_path: Path = Path("vault")
    modules_path: Path = Path("modules")
    data_dir: Path = Path("data")
    host: str = "127.0.0.1"
    port: int = 8775

    # Context layer
    embeddings_provider: str = "fastembed"  # "fastembed" | "off"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    router_model: str = "claude-opus-4-8"
    watch_vault: bool = True

    # Read by the anthropic SDK directly via ANTHROPIC_API_KEY; tracked here only
    # so the UI can report whether it is configured.
    anthropic_api_key: str | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "atrium.db"


def get_settings() -> Settings:
    return Settings()
