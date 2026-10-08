"""What Sentinel needs from a container runtime. Docker in production, processes for development and tests."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    module: str
    port: int
    health_path: str
    metrics_path: str | None
    mem_limit_mb: int
    cpu_limit: float

    @classmethod
    def from_row(cls, row: dict) -> ServiceSpec:
        return cls(row["name"], row["module"], int(row["port"]), row["health_path"], row.get("metrics_path"),
                   int(row["mem_limit_mb"]), float(row["cpu_limit"]))


@dataclass(frozen=True)
class BuildResult:
    ok: bool
    image: str
    log: str


@dataclass(frozen=True)
class Instance:
    id: str
    url: str
    image: str
    started_at: float


@dataclass(frozen=True)
class InstanceStatus:
    running: bool
    exit_code: int | None
    oom_killed: bool
    restarts: int
    health: str  # starting | healthy | unhealthy | none


@dataclass(frozen=True)
class Stats:
    cpu_percent: float | None  # 100 = one full core
    mem_mb: float | None
    mem_limit_mb: float | None
    cpu_limit: float | None


class Runtime(Protocol):
    name: str

    def build(self, spec: ServiceSpec, workdir: Path, tag: str) -> BuildResult: ...
    def run(self, spec: ServiceSpec, image: str) -> Instance: ...
    def stop(self, instance_id: str) -> None: ...
    def status(self, instance_id: str) -> InstanceStatus: ...
    def stats(self, instance_id: str) -> Stats: ...
    def logs(self, instance_id: str, tail: int = 200) -> list[str]: ...
    def remove_image(self, image: str) -> None: ...
    def shutdown(self) -> None: ...
