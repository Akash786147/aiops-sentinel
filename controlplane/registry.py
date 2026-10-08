"""Adding services: the bundled samples or any git repository with a Dockerfile."""
from __future__ import annotations

import json
import re

from controlplane.core import Core

NAME = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


def _manifest(core: Core, service: str) -> dict:
    path = core.workspace(service).root / "sentinel.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _row(core: Core, name: str, source: str, kind: str, manifest: dict, overrides: dict) -> dict:
    s = core.settings
    row = {"name": name, "source": source, "kind": kind, "package": manifest.get("package"),
           "module": manifest.get("module"), "port": manifest.get("port", 8000), "health_path": manifest.get("health_path", "/health"),
           "metrics_path": manifest.get("metrics_path"), "mem_limit_mb": s.default_mem_limit_mb, "cpu_limit": s.default_cpu_limit,
           "owner": manifest.get("owner", "unassigned"), "auto_rollback": True}
    row.update({k: v for k, v in overrides.items() if v is not None})
    return row


def register_sample(core: Core, name: str, **overrides) -> dict:
    if core.store.get_service(name):
        raise ValueError(f"service {name} already exists")
    source = core.settings.samples_dir / name
    if not (source / "sentinel.json").exists():
        raise ValueError(f"no bundled sample called {name}")
    core.workspace(name).init_from_dir(source, f"Import sample service {name}")
    row = _row(core, name, f"sample:{name}", "sample", _manifest(core, name), overrides)
    core.store.add_service(row)
    core.audit("user", "service_added", service=name, source=row["source"])
    return core.store.get_service(name)


def register_git(core: Core, name: str, url: str, branch: str | None = None, **overrides) -> dict:
    if not NAME.match(name):
        raise ValueError("name must be lowercase letters, digits and dashes (2-31 characters)")
    if core.store.get_service(name):
        raise ValueError(f"service {name} already exists")
    if not re.match(r"^(https://|git@|ssh://|file://|/)", url):
        raise ValueError("unsupported repository URL")
    ws = core.workspace(name)
    ws.clone(url, branch)
    if not (ws.root / "Dockerfile").exists() and core.settings.runtime == "docker":
        raise ValueError("the repository has no Dockerfile at its root")
    row = _row(core, name, url, "git", _manifest(core, name), overrides)
    if not row["module"] and core.settings.runtime == "process":
        raise ValueError("process runtime needs a sentinel.json with a uvicorn module")
    core.store.add_service(row)
    core.audit("user", "service_added", service=name, source=url)
    return core.store.get_service(name)
