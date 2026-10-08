"""Step 1 (shared server): which services run on the server, where their code is, who owns them."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Service:
    name: str
    owner: str
    path: str
    module: str
    port: int

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@dataclass(frozen=True)
class Registry:
    server: str
    services: tuple[Service, ...]
    shared_code: tuple[str, ...]

    def get(self, name: str) -> Service:
        for service in self.services:
            if service.name == name:
                return service
        raise KeyError(name)

    def owner_of_path(self, relative_path: str) -> str | None:
        """Map a repository path (``orders/pricing.py``) to the service that owns it."""
        first = relative_path.replace("\\", "/").split("/", 1)[0]
        for service in self.services:
            if service.path == first:
                return service.name
        return None


def load_registry(workspace: str | Path) -> Registry:
    raw = yaml.safe_load((Path(workspace) / "services.yaml").read_text(encoding="utf-8"))
    services = tuple(Service(**item) for item in raw["services"])
    return Registry(raw["server"], services, tuple(raw.get("shared_code", [])))
