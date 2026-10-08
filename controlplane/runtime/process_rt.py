"""Process runtime: Docker-like semantics without Docker (development, tests, Windows).

* build   = copy the working copy into ``builds/<service>/<tag>`` and byte-compile it (syntax errors fail the build)
* run     = ``python -m uvicorn <module>`` in that snapshot on a free port
* limits  = the watchdog kills the process when RSS exceeds the memory limit and reports ``oom_killed``
* restart = on-failure, at most ``max_restarts`` times (like ``--restart on-failure:3``)
* health  = the watchdog polls the health path; three failures in a row = unhealthy
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import psutil

from controlplane.runtime.base import BuildResult, Instance, InstanceStatus, ServiceSpec, Stats

IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "logs", "sentinel_generated")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class _Proc:
    spec: ServiceSpec
    image: str
    port: int
    log_path: Path
    process: subprocess.Popen | None = None
    restarts: int = 0
    exit_code: int | None = None
    oom_killed: bool = False
    stopped: bool = False
    health: str = "starting"
    failures: int = 0
    started_at: float = field(default_factory=time.time)
    lines: deque = field(default_factory=lambda: deque(maxlen=2000))


class ProcessRuntime:
    name = "process"

    def __init__(self, home: Path, check_interval: float = 1.0, max_restarts: int = 3) -> None:
        self.home = Path(home)
        self.check_interval = check_interval
        self.max_restarts = max_restarts
        self._procs: dict[str, _Proc] = {}
        self._lock = threading.RLock()
        self._halt = threading.Event()
        self._watch = threading.Thread(target=self._watchdog, daemon=True)
        self._watch.start()

    # build ----------------------------------------------------------------------------------
    def build(self, spec: ServiceSpec, workdir: Path, tag: str) -> BuildResult:
        target = self.home / "builds" / spec.name / tag
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(workdir, target, ignore=IGNORE)
        done = subprocess.run([sys.executable, "-m", "compileall", "-q", str(target)], capture_output=True, text=True, check=False)
        log = (done.stdout + done.stderr).strip()
        return BuildResult(done.returncode == 0, str(target), log or "build ok")

    def remove_image(self, image: str) -> None:
        shutil.rmtree(image, ignore_errors=True)

    # run ------------------------------------------------------------------------------------
    def run(self, spec: ServiceSpec, image: str) -> Instance:
        inst_id = f"{spec.name}-{uuid.uuid4().hex[:8]}"
        port = _free_port()
        run_dir = self.home / "runs" / inst_id
        run_dir.mkdir(parents=True, exist_ok=True)
        proc = _Proc(spec, image, port, run_dir / "out.log")
        with self._lock:
            self._procs[inst_id] = proc
            self._launch(proc)
        return Instance(inst_id, f"http://127.0.0.1:{port}", image, proc.started_at)

    def _launch(self, proc: _Proc) -> None:
        env = {**os.environ, "PYTHONPATH": proc.image, "SENTINEL_LOG_DIR": str(proc.log_path.parent / "logs"), "PYTHONDONTWRITEBYTECODE": "1"}
        env = {k: v for k, v in env.items() if not k.upper().endswith(("_API_KEY", "_TOKEN"))}
        handle = proc.log_path.open("ab")
        proc.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", proc.spec.module, "--host", "127.0.0.1", "--port", str(proc.port), "--log-level", "info"],
            cwd=proc.image, env=env, stdout=handle, stderr=subprocess.STDOUT)
        handle.close()
        proc.exit_code, proc.health, proc.failures = None, "starting", 0

    def stop(self, instance_id: str) -> None:
        with self._lock:
            proc = self._procs.get(instance_id)
            if not proc:
                return
            proc.stopped = True
        if proc.process and proc.process.poll() is None:
            proc.process.terminate()
            try:
                proc.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.process.kill()
        proc.exit_code = proc.process.poll() if proc.process else None

    def shutdown(self) -> None:
        self._halt.set()
        for inst_id in list(self._procs):
            self.stop(inst_id)

    # observe --------------------------------------------------------------------------------
    def status(self, instance_id: str) -> InstanceStatus:
        proc = self._procs.get(instance_id)
        if not proc:
            return InstanceStatus(False, None, False, 0, "none")
        code = proc.process.poll() if proc.process else None
        running = bool(proc.process) and code is None
        exit_code = None if running else (proc.exit_code if proc.exit_code is not None else code)
        return InstanceStatus(running, exit_code, proc.oom_killed, proc.restarts, proc.health if running else "none")

    def stats(self, instance_id: str) -> Stats:
        proc = self._procs.get(instance_id)
        if not proc or not proc.process or proc.process.poll() is not None:
            return Stats(None, None, proc.spec.mem_limit_mb if proc else None, proc.spec.cpu_limit if proc else None)
        try:
            ps = psutil.Process(proc.process.pid)
            return Stats(ps.cpu_percent(interval=0.05), round(ps.memory_info().rss / 2**20, 1), proc.spec.mem_limit_mb, proc.spec.cpu_limit)
        except psutil.Error:
            return Stats(None, None, proc.spec.mem_limit_mb, proc.spec.cpu_limit)

    def logs(self, instance_id: str, tail: int = 200) -> list[str]:
        proc = self._procs.get(instance_id)
        if not proc or not proc.log_path.exists():
            return []
        return proc.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]

    # watchdog -------------------------------------------------------------------------------
    def _watchdog(self) -> None:
        with httpx.Client(timeout=1.0) as client:
            while not self._halt.wait(self.check_interval):
                for proc in list(self._procs.values()):
                    try:
                        self._check(proc, client)
                    except Exception:  # noqa: BLE001, S112 - the watchdog must keep watching the other instances
                        continue

    def _check(self, proc: _Proc, client: httpx.Client) -> None:
        if proc.stopped or not proc.process:
            return
        code = proc.process.poll()
        if code is None:
            rss = psutil.Process(proc.process.pid).memory_info().rss / 2**20
            if rss > proc.spec.mem_limit_mb:
                proc.process.kill()
                proc.process.wait(timeout=5)
                proc.oom_killed = True
                code = 137
            else:
                try:
                    ok = client.get(f"http://127.0.0.1:{proc.port}{proc.spec.health_path}").status_code == 200
                except httpx.HTTPError:
                    ok = False
                proc.failures = 0 if ok else proc.failures + 1
                if ok:
                    proc.health = "healthy"
                elif proc.failures >= 3 and time.time() - proc.started_at > 5:
                    proc.health = "unhealthy"
                return
        proc.exit_code = code
        if code != 0 and proc.restarts < self.max_restarts:
            with self._lock:
                proc.restarts += 1
                proc.started_at = time.time()
                self._launch(proc)
