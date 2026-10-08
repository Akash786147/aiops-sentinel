"""Test lab: sample faults you can put into a monitored service, then Restart to watch Sentinel react.

* benchmark faults (F01-F12) for the sample service whose files they touch
* generic faults for any service with a FastAPI ``<package>/app.py``: start-up crash, memory leak, CPU burn
Applying writes to the working copy only; nothing runs until someone presses Restart.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass

from benchmark.scenarios import SCENARIOS
from controlplane.core import Core

EXPECT = {
    "latency": "Latency regression → incident 'regression' → investigation → proposed fix (no automatic rollback)",
    "cpu": "Slower, CPU-heavier requests → incident 'regression' or 'cpu' → investigation → proposed fix",
    "errors": "5xx errors with stack traces → incident 'regression' → investigation from the traceback → proposed fix",
    "memory": "Memory grows request by request → memory guard / OOM kill → automatic rollback to last good → investigation",
}


@dataclass(frozen=True)
class Generic:
    id: str
    title: str
    description: str
    expect: str
    snippet: str


GENERIC = (
    Generic("crash_on_start", "Crash on start-up", "Reads a secret that is not configured and raises while the app module imports.",
            "New version never becomes healthy → failed deployment, the old version keeps serving → investigation from the traceback",
            '\n\nraise RuntimeError("PAYMENT_KEY is not configured")  # injected by the Sentinel test lab\n'),
    Generic("oom_leak", "Memory leak (4 MiB per request)", "Keeps every request's buffer in a module-level list.",
            "Memory climbs to the container limit → OOM kill / memory guard → automatic rollback to last good → investigation",
            '\n\n_REQUEST_HISTORY = []  # injected by the Sentinel test lab\n\n\n@app.middleware("http")\n'
            "async def remember_request(request, call_next):\n    _REQUEST_HISTORY.append(bytearray(4 * 1024 * 1024))\n"
            "    return await call_next(request)\n"),
    Generic("cpu_spin", "CPU burn on every request", "Recomputes a large checksum for each request.",
            "CPU pinned at the limit → CPU guard incident → investigation → proposed fix (no automatic rollback)",
            '\n\n@app.middleware("http")  # injected by the Sentinel test lab\nasync def checksum_request(request, call_next):\n'
            "    sum(i * i for i in range(400_000))\n    return await call_next(request)\n"),
)


def _app_file(core: Core, service: str) -> str | None:
    svc = core.store.get_service(service)
    module = (svc.get("module") or "").split(":")[0]
    if not module:
        return None
    rel = module.replace(".", "/") + ".py"
    return rel if (core.workspace(service).root / rel).exists() else None


def _changes(core: Core, service: str, recipe_id: str) -> dict[str, tuple[str, str]]:
    """{file: (before, after)} for the recipe against the current working copy."""
    ws = core.workspace(service)
    generic = next((g for g in GENERIC if g.id == recipe_id), None)
    if generic:
        rel = _app_file(core, service)
        if not rel:
            raise KeyError(f"{recipe_id} needs a FastAPI app module")
        before = ws.read(rel)
        return {rel: (before, before.rstrip("\n") + "\n" + generic.snippet)}
    scenario = next((s for s in SCENARIOS if s.id == recipe_id and s.fault), None)
    if scenario is None:
        raise KeyError(f"unknown recipe {recipe_id}")
    out = {}
    for patch in scenario.fault.patches:
        before = out.get(patch.file, (None, None))[1] or ws.read(patch.file)
        if before.count(patch.old) != 1:
            raise ValueError(f"{recipe_id} does not apply to the current {patch.file}")
        out[patch.file] = (out.get(patch.file, (before, None))[0], before.replace(patch.old, patch.new))
    return out


def catalog(core: Core, service: str) -> list[dict]:
    ws, svc = core.workspace(service), core.store.get_service(service)
    recipes = []
    for scenario in SCENARIOS:
        if not scenario.fault or scenario.service != svc.get("package"):
            continue
        files = [p.file for p in scenario.fault.patches]
        available = all((ws.root / p.file).exists() and ws.read(p.file).count(p.old) == 1 for p in scenario.fault.patches)
        recipes.append({"id": scenario.id, "title": scenario.title, "kind": "benchmark", "class": scenario.fault_class, "files": files,
                        "description": f"Benchmark fault {scenario.id}, shipped as the commit \"{scenario.fault.message}\".",
                        "expect": EXPECT[scenario.fault_class], "available": available})
    app_file = _app_file(core, service)
    for g in GENERIC:
        available = bool(app_file) and g.snippet.strip().splitlines()[0] not in ws.read(app_file)
        recipes.append({"id": g.id, "title": g.title, "kind": "generic", "class": g.id, "files": [app_file] if app_file else [],
                        "description": g.description, "expect": g.expect, "available": available})
    return recipes


def preview(core: Core, service: str, recipe_id: str) -> str:
    out = []
    for rel, (before, after) in _changes(core, service, recipe_id).items():
        out.extend(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), f"a/{rel}", f"b/{rel}"))
    return "".join(out)


def apply(core: Core, service: str, recipe_id: str, actor: str) -> list[str]:
    with core.locks.hold(service):
        changes = _changes(core, service, recipe_id)
        ws = core.workspace(service)
        for rel, (_, after) in changes.items():
            ws.write(rel, after)
        core.audit(actor, "lab_fault_applied", service=service, recipe=recipe_id, files=sorted(changes))
        return sorted(changes)


def reset(core: Core, service: str, actor: str) -> str:
    """Working copy back to the last good version (or to HEAD when there is none yet)."""
    with core.locks.hold(service):
        ws = core.workspace(service)
        good = core.store.last_good(service)
        if good:
            ws.restore(good["commit"])
        else:
            ws.discard()
        core.audit(actor, "lab_reset", service=service, to=(good["commit"][:12] if good else "HEAD"))
        return good["commit"] if good else ws.head()
