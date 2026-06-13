"""Module manifest — the static metadata in each module's ``module.toml``.

Parsed and validated without importing the module's code, so a broken module
can still be listed (with an error status) in the registry.
"""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

TriggerType = Literal["continuous", "schedule", "webhook", "manual"]


class ManifestTriggers(BaseModel):
    supported: list[TriggerType] = Field(default_factory=lambda: ["manual"])
    # Optional default trigger suggestion, e.g. {type = "schedule", cron = "*/30 * * * *"}.
    # Stored as-is; actual triggers are created/edited via the API (Phase 2).
    default: dict | None = None

    @field_validator("supported")
    @classmethod
    def manual_always_supported(cls, v: list[TriggerType]) -> list[TriggerType]:
        if "manual" not in v:
            v = [*v, "manual"]
        return v


class ManifestContext(BaseModel):
    """Vault path prefixes this module may read/write (enforced by the librarian)."""

    read: list[str] = Field(default_factory=list)
    write: list[str] = Field(default_factory=list)


class ModuleManifest(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str
    version: str = "0.1.0"
    description: str = ""
    kind: Literal["agent", "automation"] = "automation"
    timeout_seconds: float = Field(default=300.0, gt=0)
    triggers: ManifestTriggers = Field(default_factory=ManifestTriggers)
    context: ManifestContext = Field(default_factory=ManifestContext)

    @classmethod
    def from_toml(cls, path: Path) -> "ModuleManifest":
        with path.open("rb") as f:
            data = tomllib.load(f)
        section = data.get("module")
        if section is None:
            raise ValueError(f"{path}: missing [module] table")
        return cls.model_validate(section)
