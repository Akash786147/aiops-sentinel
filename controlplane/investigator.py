"""Investigates a live incident with the existing Sentinel pipeline and proposes a fix a human can approve.

1. Pin the two versions: ``deploy-prev`` = last good commit, ``deploy-current`` = the incident's commit
   (a git worktree of the incident commit is the "faulty" tree; an export of last good is the "known-good" tree).
2. Evidence packet (sentinel.context): signals, exceptions (JSON log lines and plain tracebacks from the
   container logs), slow/failed requests, the behavioural diff between the two versions.
3. Hybrid trace (sentinel.tracing) plus optional LLM re-rank.
4. Confirming tests (sentinel.testgen): template or start-up test, plus LLM test; fail on faulty, pass on good.
5. Proposed patch: LLM diff validated with ``git apply --check``, otherwise a deterministic revert of the suspect
   files to their last-good content. Approve applies it and deploys through the normal Restart flow.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from controlplane.core import Core
from controlplane.locks import Busy
from sentinel import llm
from sentinel.context import build_packet, redact, route_baseline_stats
from sentinel.detection import Incident as DetectionIncident
from sentinel.detection import Signal
from sentinel.indexing import CodeIndex
from sentinel.registry import Registry
from sentinel.registry import Service as RegistryService
from sentinel.testgen import confirm, guard, llm_test, template_test
from sentinel.tracing import decide, incident_query, llm_rerank, rank

KIND_SYMPTOM = {"crash": "errors", "crash_loop": "errors", "build": "errors", "alert": "errors", "oom": "memory", "memory": "memory",
                "cpu": "cpu", "unhealthy": "latency", "regression": "latency"}
STARTUP_KINDS = {"crash", "crash_loop", "build", "unhealthy"}
FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.+)$')
EXC_LINE = re.compile(r"^(?P<type>[A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning)):\s*(?P<msg>.*)$")
PATCH_PROMPT = """You fix a regression in a service. The diff below is the change that went live; the evidence shows what broke.
Return ONLY a unified diff (git format, paths relative to the repository root, a/ and b/ prefixes) that fixes the root cause with
the smallest change. Do not touch tests, CI, Dockerfiles or configuration of the platform. No prose."""


class NotApprovable(RuntimeError):
    """The incident has no patch that can be applied."""


def parse_tracebacks(lines: list[str], repo_files: list[str], service: str, at: float | None = None) -> list[dict]:
    """Plain-text Python tracebacks (start-up crashes) → exception events with repo-relative frames."""
    events, frames, inside = [], [], False
    for line in lines:
        if line.startswith("Traceback (most recent call last):"):
            inside, frames = True, []
            continue
        if not inside:
            continue
        match = FRAME.match(line)
        if match:
            path = match["file"].replace("\\", "/")
            rel = next((f for f in repo_files if path.endswith("/" + f) or path == f), None)
            if rel:
                frames.append({"file": rel, "line": int(match["line"]), "function": match["func"].strip()})
            continue
        exc = EXC_LINE.match(line.strip())
        if exc:
            events.append({"at": at or time.time(), "service": service, "level": "error", "path": "(start-up)", "method": "-", "body": "",
                           "exception": exc["type"].rsplit(".", 1)[-1], "message": exc["msg"][:500], "frames": frames})
            inside = False
    return events


def parse_json_events(lines: list[str]) -> list[dict]:
    events = []
    for line in lines:
        start = line.find("{")
        if start < 0 or '"exception"' not in line:
            continue
        try:
            event = json.loads(line[start:])
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("exception") and "frames" in event:
            events.append(event)
    return events


def startup_test(module: str, hypothesis: str) -> str:
    return f'''"""Sentinel-generated confirming test: the service must start.

Hypothesis: {hypothesis}
"""


def test_service_imports_and_answers_health():
    try:
        from {module} import app
    except Exception as exc:  # the start-up crash itself is the failure we expect on the faulty version
        raise AssertionError(f"service failed to start: {{type(exc).__name__}}: {{exc}}") from exc
    from fastapi.testclient import TestClient

    assert TestClient(app).get("/health").status_code == 200
'''


class Investigator:
    def __init__(self, core: Core, monitor, deployer, use_llm: bool = True, dense: bool = True) -> None:
        self.core, self.monitor, self.deployer = core, monitor, deployer
        self.use_llm, self.dense = use_llm, dense

    # investigation --------------------------------------------------------------------------
    def investigate(self, inc_id: int) -> dict:
        store = self.core.store
        inc = store.get_incident(inc_id)
        svc = store.get_service(inc["service"])
        if inc["status"] == "open":
            store.update_incident(inc_id, status="investigating")
        self.core.audit("sentinel", "investigation_started", service=svc["name"], incident_id=inc_id)
        self.core.bus.emit("incident", store.get_incident(inc_id))
        try:
            result = self._investigate(inc, svc)
        except Exception as exc:
            store.update_incident(inc_id, diagnosis={"error": f"{type(exc).__name__}: {exc}"},
                                  status="needs_attention" if inc["status"] != "rolled_back" else "rolled_back")
            self.core.audit("sentinel", "investigation_failed", service=svc["name"], incident_id=inc_id, error=str(exc))
            self.core.bus.emit("incident", store.get_incident(inc_id))
            raise
        status = store.get_incident(inc_id)["status"]
        store.update_incident(inc_id, diagnosis=result, patch=result["patch"].pop("text", None),
                              status="diagnosed" if status in ("open", "investigating") else status)
        self.core.audit("sentinel", "investigated", service=svc["name"], incident_id=inc_id,
                        top=result["suspects"][0]["chunk_id"] if result["suspects"] else None,
                        confirming={k: v["confirming"] for k, v in result["tests"].items()}, patch=result["patch"]["source"])
        self.core.bus.emit("incident", store.get_incident(inc_id))
        return result

    def _versions(self, inc: dict) -> tuple[dict, str, str]:
        store, ws = self.core.store, self.core.workspace(inc["service"])
        bad = store.get_deployment(inc["deployment_id"]) if inc["deployment_id"] else store.current_deployment(inc["service"])
        good = store.last_good(inc["service"])
        if good and good["commit"] != bad["commit"]:
            prev = good["commit"]
        else:
            parents = ws.git("rev-list", "--parents", "-n", "1", bad["commit"]).split()
            prev = parents[1] if len(parents) > 1 else bad["commit"]
        return bad, prev, bad["commit"]

    def _investigate(self, inc: dict, svc: dict) -> dict:
        name, ws = svc["name"], self.core.workspace(svc["name"])
        bad, prev_sha, bad_sha = self._versions(inc)
        work = self.core.settings.runs_dir / f"inc-{inc['id']}"
        faulty = work / "faulty"
        if faulty.exists():
            ws.git("worktree", "remove", "--force", str(faulty), check=False)
            shutil.rmtree(faulty, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        ws.git("worktree", "prune")
        ws.git("worktree", "add", "--detach", str(faulty), bad_sha)
        good_tree = ws.export(prev_sha, work / "good")
        ws.tag("deploy-prev", prev_sha)
        ws.tag("deploy-current", bad_sha)

        start = bad.get("healthy_at") or bad["created_at"]
        window = (min(start, inc["opened_at"]) - 5, time.time())
        samples = self.monitor.series(name) if self.monitor else []
        files = ws.git("ls-tree", "-r", "--name-only", bad_sha).split()
        log_lines = (bad.get("detail") or {}).get("logs", "").splitlines()
        if bad.get("instance"):
            log_lines += self.core.runtime.logs(bad["instance"], 400)
        exceptions = parse_json_events(log_lines) + parse_tracebacks(log_lines, files, name, at=window[0] + 1)
        (faulty / "logs").mkdir(exist_ok=True)
        (faulty / "logs" / f"{name}.jsonl").write_text("".join(json.dumps({**e, "at": max(e.get("at", 0), window[0] + 1)}) + "\n" for e in exceptions),
                                                        encoding="utf-8")

        manifest_path = faulty / "sentinel.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        registry = Registry("sentinel", (RegistryService(name, svc["owner"], svc["package"] or ".", svc["module"] or "", int(svc["port"])),),
                            tuple(manifest.get("shared_code", [])))
        signals = [Signal(s["kind"], s.get("name", s["kind"]), s.get("route"), s.get("baseline", 0), s.get("observed", 0), s.get("z", 0),
                          s.get("anomalous_buckets", 0)) for s in inc["signals"] if "baseline" in s and "observed" in s]
        symptoms = list(dict.fromkeys([s.kind for s in signals] or [KIND_SYMPTOM.get(inc["kind"], "errors")]))
        if exceptions and "errors" not in symptoms:
            symptoms.append("errors")
        det = DetectionIncident(f"INC-{inc['id']}", name, symptoms, signals, window, max([s.z for s in signals] or [0]))
        packet = build_packet(faulty, registry, det, samples)
        try:
            index = CodeIndex(faulty, dense=self.dense)
        except Exception:  # noqa: BLE001 - embeddings are optional (no model download, no memory)
            index = CodeIndex(faulty, dense=False)
        suspects = rank(index, packet, registry, scoped=bool(svc["package"]))
        decision = decide(packet.incident, suspects)
        hypothesis = f"{suspects[0].symbol} in {suspects[0].path}" if suspects else "unknown"
        llm_meta = None
        if self.use_llm and llm.available() and suspects:
            reranked, llm_meta = llm_rerank(index, packet, suspects)
            if llm_meta.get("valid"):
                suspects = reranked
                hypothesis = llm_meta.get("root_cause") or hypothesis

        module = (svc["module"] or "").split(":")[0]
        tests: dict[str, dict] = {}
        if module:
            if inc["kind"] in STARTUP_KINDS and (exceptions or not samples):
                code = startup_test(module, hypothesis)
            else:
                routes = {r["route"] for r in packet.slow_or_failed_requests + packet.exemplar_requests}
                baselines = {r: route_baseline_stats(samples, name, r, start) for r in routes}
                baselines = {k: v for k, v in baselines.items() if v}
                code = template_test(packet, module, baselines, hypothesis)
            tests["template"] = {"code": code, **(confirm(faulty, good_tree, code) if code else {"confirming": False, "guard": ["no test generated"]})}
            if self.use_llm and llm.available() and suspects:
                routes = {r["route"] for r in packet.slow_or_failed_requests + packet.exemplar_requests}
                baselines = {r: v for r in routes if (v := route_baseline_stats(samples, name, r, start))}
                code, meta = llm_test(index, packet, module, suspects, baselines, hypothesis)
                tests["llm"] = {"code": code, **(confirm(faulty, good_tree, code) if code else {"confirming": False, "guard": ["no test generated"]}), "meta": meta}

        patch = self._propose(ws, packet, index, suspects, prev_sha, bad_sha)
        ws.git("worktree", "remove", "--force", str(faulty), check=False)
        return {
            "suspects": [asdict(s) for s in suspects[:10]],
            "decision": decision,
            "hypothesis": hypothesis,
            "llm": {k: v for k, v in (llm_meta or {}).items() if k != "messages"} or None,
            "tests": tests,
            "exceptions": packet.exceptions[:5],
            "symptoms": symptoms,
            "packet": {"digest": packet.digest, "commits": packet.commits, "changes": [asdict(c) for c in packet.changes], "query": incident_query(packet)},
            "versions": {"good": prev_sha, "bad": bad_sha},
            "patch": patch,
            "finished_at": time.time(),
        }

    # proposed patch -------------------------------------------------------------------------
    def _applies(self, ws, patch: str) -> bool:
        if not patch.strip():
            return False
        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False, encoding="utf-8", newline="\n") as handle:
            handle.write(patch if patch.endswith("\n") else patch + "\n")
            path = handle.name
        try:
            done = subprocess.run(["git", "apply", "--check", path], cwd=ws.root, capture_output=True, text=True, check=False)
            return done.returncode == 0
        finally:
            Path(path).unlink(missing_ok=True)

    def _propose(self, ws, packet, index, suspects, prev_sha: str, bad_sha: str) -> dict:
        changed = sorted({c.file for c in packet.changes if c.behavioural}) or sorted({c.file for c in packet.changes})
        suspect_files = list(dict.fromkeys(s.path for s in suspects[:3] if s.path in changed))
        files = suspect_files or changed
        if self.use_llm and llm.available() and suspects:
            text = self._llm_patch(ws, packet, index, suspects, prev_sha, bad_sha)
            if text and self._applies(ws, text):
                return {"source": "llm", "applies": True, "files": re.findall(r"^\+\+\+ b/(.+)$", text, re.MULTILINE), "text": text,
                        "summary": "LLM-proposed fix for the top suspect"}
        text = ws.git("diff", bad_sha, prev_sha, "--", *files) if files else ""
        applies = self._applies(ws, text)
        summary = f"Revert {', '.join(files)} to the last good version ({prev_sha[:7]})" if files else "No code change to revert"
        return {"source": "revert", "applies": applies, "files": files, "text": text, "summary": summary}

    def _llm_patch(self, ws, packet, index, suspects, prev_sha: str, bad_sha: str) -> str | None:
        chunks = {c.id: c for c in index.chunks}
        code = "\n\n".join(f"# {s.path} lines {s.start}-{s.end}\n{chunks[s.chunk_id].text}" for s in suspects[:3] if s.chunk_id in chunks)
        diff = ws.git("diff", prev_sha, bad_sha)[:6000]
        user = f"Evidence:\n{packet.to_text()}\n\nChange that went live:\n```diff\n{diff}\n```\n\nSuspect code:\n```python\n{code}\n```"
        try:
            result = llm.chat([{"role": "system", "content": PATCH_PROMPT}, {"role": "user", "content": redact(user)}], max_tokens=1500)
        except Exception:  # noqa: BLE001 - the deterministic revert is the fallback
            return None
        match = re.search(r"```(?:diff|patch)?\n(.*?)```", result.text, re.DOTALL)
        return (match.group(1) if match else result.text).strip() + "\n"

    # human decisions ------------------------------------------------------------------------
    def approve(self, inc_id: int, approver: str, note: str = "") -> dict:
        store = self.core.store
        inc = store.get_incident(inc_id)
        meta = (inc.get("diagnosis") or {}).get("patch") or {}
        if not inc.get("patch") or not meta.get("applies"):
            raise NotApprovable("this incident has no patch that applies")
        if inc["status"] in ("resolved", "dismissed"):
            raise NotApprovable(f"incident is already {inc['status']}")
        ws = self.core.workspace(inc["service"])
        with self.core.locks.hold(inc["service"]):
            if not self._applies(ws, inc["patch"]):
                raise NotApprovable("the patch no longer applies to the current code")
            with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False, encoding="utf-8", newline="\n") as handle:
                handle.write(inc["patch"])
                path = handle.name
            try:
                subprocess.run(["git", "apply", path], cwd=ws.root, capture_output=True, text=True, check=True)
            finally:
                Path(path).unlink(missing_ok=True)
            message = f"Sentinel fix for INC-{inc_id}: {meta.get('summary', 'approved patch')} (approved by {approver})"
            dep = self.deployer._deploy(inc["service"], "approve", approver, message)
        if dep["status"] == "healthy":
            store.update_incident(inc_id, status="resolved")
            self.core.audit(approver, "approved_fix", service=inc["service"], incident_id=inc_id, deployment=dep["id"], note=note)
        else:
            self.core.audit(approver, "approved_fix_failed", service=inc["service"], incident_id=inc_id, deployment=dep["id"], note=note)
        self.core.bus.emit("incident", store.get_incident(inc_id))
        return dep

    def dismiss(self, inc_id: int, actor: str, note: str = "") -> dict:
        self.core.store.update_incident(inc_id, status="dismissed")
        self.core.audit(actor, "dismissed", service=self.core.store.get_incident(inc_id)["service"], incident_id=inc_id, note=note)
        inc = self.core.store.get_incident(inc_id)
        self.core.bus.emit("incident", inc)
        return inc


__all__ = ["Busy", "Investigator", "NotApprovable", "guard", "parse_json_events", "parse_tracebacks", "startup_test"]
