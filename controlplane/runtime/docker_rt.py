"""Docker runtime: Sentinel builds each service image and runs it as a labelled, resource-limited container.

Labels make the container visible to the rest of the stack:
* Prometheus discovers it (``sentinel.monitor=true``) and scrapes ``/metrics`` on ``sentinel.metrics_port``
* Traefik routes ``/svc/<name>`` to it (both instances share the router while a deploy swaps them)
* Promtail tags its logs with ``sentinel.service``
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import docker

from controlplane.runtime.base import BuildResult, Instance, InstanceStatus, ServiceSpec, Stats


class DockerRuntime:
    name = "docker"

    def __init__(self, network: str = "sentinel", client=None) -> None:
        self.client = client or docker.from_env()
        self.network = network

    def build(self, spec: ServiceSpec, workdir: Path, tag: str) -> BuildResult:
        image = f"sentinel/{spec.name}:{tag}"
        try:
            _, chunks = self.client.images.build(path=str(workdir), tag=image, rm=True, forcerm=True, pull=False,
                                                 labels={"sentinel.service": spec.name})
            return BuildResult(True, image, "".join(c.get("stream", "") for c in chunks)[-6000:])
        except docker.errors.BuildError as exc:
            text = "".join(c.get("stream", "") or c.get("error", "") for c in exc.build_log)
            return BuildResult(False, image, text[-6000:] or str(exc))
        except docker.errors.APIError as exc:
            return BuildResult(False, image, str(exc))

    def labels(self, spec: ServiceSpec) -> dict[str, str]:
        router = f"svc-{spec.name}"
        return {
            "sentinel.monitor": "true",
            "sentinel.service": spec.name,
            "sentinel.metrics_port": str(spec.port),
            "sentinel.metrics_path": "/metrics",
            "traefik.enable": "true",
            "traefik.docker.network": self.network,
            f"traefik.http.routers.{router}.rule": f"PathPrefix(`/svc/{spec.name}`)",
            f"traefik.http.routers.{router}.entrypoints": "web",
            f"traefik.http.routers.{router}.middlewares": f"{router}-strip",
            f"traefik.http.middlewares.{router}-strip.stripprefix.prefixes": f"/svc/{spec.name}",
            f"traefik.http.services.{router}.loadbalancer.server.port": str(spec.port),
        }

    def run(self, spec: ServiceSpec, image: str) -> Instance:
        tag = image.rsplit(":", 1)[-1][:12]
        name = f"svc-{spec.name}-{tag}-{uuid.uuid4().hex[:4]}"
        container = self.client.containers.run(
            image, name=name, detach=True, network=self.network, labels=self.labels(spec),
            mem_limit=f"{spec.mem_limit_mb}m", memswap_limit=f"{spec.mem_limit_mb}m", nano_cpus=int(spec.cpu_limit * 1e9),
            restart_policy={"Name": "on-failure", "MaximumRetryCount": 3},
            environment={"SENTINEL_SERVICE": spec.name, "SENTINEL_LOG_DIR": "/app/logs"},
        )
        return Instance(container.id, f"http://{name}:{spec.port}", image, time.time())

    def _get(self, instance_id: str):
        try:
            container = self.client.containers.get(instance_id)
            container.reload()
            return container
        except docker.errors.NotFound:
            return None

    def stop(self, instance_id: str) -> None:
        container = self._get(instance_id)
        if container is None:
            return
        try:
            container.stop(timeout=5)
        finally:
            container.remove(v=True, force=True)

    def status(self, instance_id: str) -> InstanceStatus:
        container = self._get(instance_id)
        if container is None:
            return InstanceStatus(False, None, False, 0, "none")
        state = container.attrs["State"]
        running = state.get("Status") == "running"
        return InstanceStatus(running, None if running else state.get("ExitCode"), bool(state.get("OOMKilled")),
                              int(container.attrs.get("RestartCount", 0)), (state.get("Health") or {}).get("Status", "none"))

    def stats(self, instance_id: str) -> Stats:
        container = self._get(instance_id)
        if container is None:
            return Stats(None, None, None, None)
        raw = container.stats(stream=False)
        cpu, pre = raw.get("cpu_stats", {}), raw.get("precpu_stats", {})
        cpu_delta = cpu.get("cpu_usage", {}).get("total_usage", 0) - pre.get("cpu_usage", {}).get("total_usage", 0)
        sys_delta = cpu.get("system_cpu_usage", 0) - pre.get("system_cpu_usage", 0)
        online = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage") or [1])
        cpu_percent = round(cpu_delta / sys_delta * online * 100, 1) if sys_delta > 0 else 0.0
        mem = raw.get("memory_stats", {})
        used = mem.get("usage", 0) - (mem.get("stats") or {}).get("inactive_file", 0)
        host = container.attrs.get("HostConfig", {})
        return Stats(cpu_percent, round(used / 2**20, 1), round(mem.get("limit", 0) / 2**20, 1) or None,
                     (host.get("NanoCpus") or 0) / 1e9 or None)

    def logs(self, instance_id: str, tail: int = 200) -> list[str]:
        container = self._get(instance_id)
        if container is None:
            return []
        return container.logs(tail=tail).decode("utf-8", errors="replace").splitlines()

    def remove_image(self, image: str) -> None:
        try:
            self.client.images.remove(image, force=False)
        except docker.errors.APIError:
            pass

    def shutdown(self) -> None:
        pass
