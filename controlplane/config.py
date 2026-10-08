"""Settings, all overridable from the environment (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    home: Path
    runtime: str = "process"  # docker | process
    network: str = "sentinel"
    samples_dir: Path = field(default=REPO / "samples")
    health_timeout_s: float = 30.0
    stability_window_s: float = 120.0
    regression_after_s: float = 60.0
    unhealthy_grace_s: float = 45.0
    memory_guard_ratio: float = 0.95
    cpu_guard_ratio: float = 0.90
    guard_hold_s: float = 30.0
    crash_loop_restarts: int = 3
    crash_loop_window_s: float = 120.0
    default_mem_limit_mb: int = 256
    default_cpu_limit: float = 0.5
    loki_url: str | None = None
    grafana_url: str = "/grafana/"
    prometheus_url: str = "/prometheus/"
    alertmanager_url: str = "/alertmanager/"
    public_host: str = "localhost"

    @property
    def db_path(self) -> Path:
        return self.home / "sentinel.db"

    @property
    def services_dir(self) -> Path:
        return self.home / "services"

    @property
    def builds_dir(self) -> Path:
        return self.home / "builds"

    @property
    def runs_dir(self) -> Path:
        return self.home / "runs"

    @classmethod
    def from_env(cls) -> Settings:
        home = Path(os.getenv("SENTINEL_HOME", REPO / "data" / "sentinel"))
        return cls(
            home=home,
            runtime=os.getenv("SENTINEL_RUNTIME", "process"),
            network=os.getenv("SENTINEL_NETWORK", "sentinel"),
            health_timeout_s=_f("SENTINEL_HEALTH_TIMEOUT_S", 30),
            stability_window_s=_f("SENTINEL_STABILITY_WINDOW_S", 120),
            regression_after_s=_f("SENTINEL_REGRESSION_AFTER_S", 60),
            unhealthy_grace_s=_f("SENTINEL_UNHEALTHY_GRACE_S", 45),
            guard_hold_s=_f("SENTINEL_GUARD_HOLD_S", 30),
            default_mem_limit_mb=int(_f("SENTINEL_DEFAULT_MEM_MB", 256)),
            default_cpu_limit=_f("SENTINEL_DEFAULT_CPUS", 0.5),
            loki_url=os.getenv("SENTINEL_LOKI_URL") or None,
            public_host=os.getenv("SENTINEL_PUBLIC_HOST", "localhost"),
        )
