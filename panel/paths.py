"""Where the console reads recordings and results and writes its own files."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def bench(self) -> Path:
        return self.root / "data" / "bench"

    @property
    def results(self) -> Path:
        return self.root / "evaluation" / "results"

    @property
    def panel_data(self) -> Path:
        return self.root / "data" / "panel"

    def recording(self, scenario: str, seed: int) -> Path:
        return self.bench / f"{scenario}-s{seed}.json"

    def run_result(self, scenario: str, seed: int) -> Path:
        return self.results / "runs" / f"{scenario}-s{seed}.json"

    def audit(self, scenario: str, seed: int) -> Path:
        return self.results / "audit" / f"{scenario}-s{seed}.jsonl"


DEFAULT = Paths(Path(__file__).resolve().parents[1])
