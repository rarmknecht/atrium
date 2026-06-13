"""Module discovery: scan the modules directory, parse manifests, import code.

Manifests are parsed *before* any module code is imported, so a module whose code
fails to import (or whose package is malformed) is still listed — with an error
status — and never breaks the platform.
"""

import importlib.util
import inspect
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from atrium.core.module import Module
from atrium.models import ModuleManifest

logger = logging.getLogger(__name__)

_NAMESPACE = "atrium_modules"


@dataclass
class ModuleRecord:
    dir_name: str
    path: Path
    manifest: ModuleManifest | None = None
    instance: Module | None = None
    status: str = "ready"  # ready | error
    error: str | None = None
    load_warnings: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.manifest.id if self.manifest else self.dir_name

    @property
    def config_model(self) -> type[BaseModel]:
        assert self.instance is not None
        return type(self.instance).ConfigModel


class ModuleRegistry:
    def __init__(self, modules_path: Path):
        self.modules_path = modules_path
        self._records: dict[str, ModuleRecord] = {}

    def scan(self) -> None:
        """(Re)discover all modules. Safe to call repeatedly."""
        self._records.clear()
        if not self.modules_path.is_dir():
            logger.warning("modules path %s does not exist", self.modules_path)
            return
        for entry in sorted(self.modules_path.iterdir()):
            if not entry.is_dir() or entry.name.startswith(("_", ".")):
                continue
            record = self._load(entry)
            if record.id in self._records:
                record.status = "error"
                record.error = f"duplicate module id {record.id!r}"
            self._records[record.id] = record
            level = logging.INFO if record.status == "ready" else logging.ERROR
            logger.log(level, "module %s: %s %s", record.id, record.status, record.error or "")

    def _load(self, path: Path) -> ModuleRecord:
        record = ModuleRecord(dir_name=path.name, path=path)

        manifest_path = path / "module.toml"
        try:
            record.manifest = ModuleManifest.from_toml(manifest_path)
        except FileNotFoundError:
            record.status, record.error = "error", "module.toml not found"
            return record
        except Exception as exc:
            record.status, record.error = "error", f"invalid manifest: {exc}"
            return record

        if record.manifest.id != path.name:
            record.load_warnings.append(
                f"directory name {path.name!r} != manifest id {record.manifest.id!r}"
            )

        try:
            record.instance = self._import_module_class(path, record.manifest.id)()
        except Exception as exc:
            record.status, record.error = "error", f"import failed: {exc}"
        return record

    def _import_module_class(self, path: Path, module_id: str) -> type[Module]:
        init = path / "__init__.py"
        if not init.is_file():
            raise FileNotFoundError("__init__.py not found")
        qualname = f"{_NAMESPACE}.{module_id}"
        spec = importlib.util.spec_from_file_location(
            qualname, init, submodule_search_locations=[str(path)]
        )
        assert spec and spec.loader
        pkg = importlib.util.module_from_spec(spec)
        sys.modules[qualname] = pkg
        try:
            spec.loader.exec_module(pkg)
        except Exception:
            sys.modules.pop(qualname, None)
            raise

        candidates = [
            obj
            for obj in vars(pkg).values()
            if inspect.isclass(obj) and issubclass(obj, Module) and not inspect.isabstract(obj)
        ]
        if not candidates:
            raise TypeError("no Module subclass exported from __init__.py")
        if len(candidates) > 1:
            names = ", ".join(c.__name__ for c in candidates)
            raise TypeError(f"expected exactly one Module subclass, found: {names}")
        return candidates[0]

    # -- queries ------------------------------------------------------------

    def all(self) -> list[ModuleRecord]:
        return list(self._records.values())

    def get(self, module_id: str) -> ModuleRecord | None:
        return self._records.get(module_id)

    def get_ready(self, module_id: str) -> ModuleRecord:
        record = self._records.get(module_id)
        if record is None:
            raise KeyError(f"unknown module {module_id!r}")
        if record.status != "ready" or record.instance is None:
            raise RuntimeError(f"module {module_id!r} is not loadable: {record.error}")
        return record
