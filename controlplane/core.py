"""Shared state of the control plane: settings, store, runtime, event bus, locks."""
from __future__ import annotations

from dataclasses import dataclass

from controlplane.config import Settings
from controlplane.locks import LockTable
from controlplane.runtime import make_runtime
from controlplane.runtime.base import Runtime
from controlplane.store import Store
from controlplane.workspace import Workspace
from panel.bus import EventBus


@dataclass
class Core:
    settings: Settings
    store: Store
    runtime: Runtime
    bus: EventBus
    locks: LockTable

    @classmethod
    def create(cls, settings: Settings, runtime: Runtime | None = None) -> Core:
        settings.home.mkdir(parents=True, exist_ok=True)
        return cls(settings, Store(settings.db_path), runtime or make_runtime(settings), EventBus(), LockTable())

    def workspace(self, service: str) -> Workspace:
        return Workspace(self.settings.services_dir / service)

    def audit(self, actor: str, action: str, service: str | None = None, incident_id: int | None = None, **detail) -> dict:
        event = self.store.audit(actor, action, service=service, incident_id=incident_id, **detail)
        self.bus.emit("audit", event)
        return event
