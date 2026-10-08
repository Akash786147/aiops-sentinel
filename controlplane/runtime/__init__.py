"""Runtime selection: Docker on the server, processes for development and tests."""
from __future__ import annotations

from controlplane.config import Settings
from controlplane.runtime.base import Runtime


def make_runtime(settings: Settings) -> Runtime:
    if settings.runtime == "docker":
        from controlplane.runtime.docker_rt import DockerRuntime

        return DockerRuntime(network=settings.network)
    from controlplane.runtime.process_rt import ProcessRuntime

    return ProcessRuntime(settings.home)
