"""Build a git workspace for one scenario: base commit, then a deployment of several commits."""
from __future__ import annotations

import os
import random
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from benchmark.scenarios import DECOYS, Commit, Patch, Scenario

SOURCE = Path(__file__).resolve().parents[1] / "shared_server"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
    "GIT_COMMITTER_NAME": "dev", "GIT_COMMITTER_EMAIL": "dev@example.com",
}


@dataclass
class GroundTruth:
    service: str | None
    file: str | None
    start_line: int | None
    end_line: int | None
    fault_commit_position: int | None  # 1 = oldest commit of the deployment


def git(cwd: Path, *args: str, date: str | None = None) -> str:
    env = {**os.environ, **GIT_ENV}
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def apply_patch(root: Path, patch: Patch, reverse: bool = False) -> None:
    old, new = (patch.new, patch.old) if reverse else (patch.old, patch.new)
    path = root / patch.file
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise ValueError(f"patch target must occur exactly once in {patch.file}: {old[:60]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def locate(root: Path, patch: Patch) -> tuple[int, int]:
    text = (root / patch.file).read_text(encoding="utf-8")
    start = text[: text.index(patch.new)].count("\n") + 1
    return start, start + patch.new.count("\n")


def deployment(scenario: Scenario, seed: int) -> list[Commit]:
    """The fault commit hidden among decoys, in a seeded random order."""
    rng = random.Random(f"{scenario.id}-{seed}")
    target_files = {p.file for c in (scenario.fault, *scenario.extra_commits) if c for p in c.patches}
    pool = [d for d in DECOYS if not {p.file for p in d.patches} & target_files]
    same_service = [d for d in pool if scenario.service and d.patches[0].file.startswith(scenario.service + "/")]
    decoys = rng.sample(same_service, 1) if same_service else []
    decoys += rng.sample([d for d in pool if d not in decoys], 3 - len(decoys))
    commits = decoys + list(scenario.extra_commits) + ([scenario.fault] if scenario.fault else [])
    rng.shuffle(commits)
    return commits


def build(scenario: Scenario, root: Path, seed: int = 0) -> tuple[list[Commit], GroundTruth]:
    """Create ``root`` at the pre-deployment state and return the commits still to deploy."""
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("__pycache__", "logs", "*.pyc"))
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Release 1.4.0", date="2026-09-01T10:00:00")
    git(root, "tag", "deploy-prev")
    commits = deployment(scenario, seed)
    position = commits.index(scenario.fault) + 1 if scenario.fault else None
    return commits, GroundTruth(scenario.service, None, None, None, position)


def deploy(root: Path, commits: list[Commit], scenario: Scenario, truth: GroundTruth) -> list[str]:
    """Apply the deployment as real commits; fill in the fault's line range. Returns changed services."""
    changed = set()
    for number, commit in enumerate(commits, start=1):
        for patch in commit.patches:
            apply_patch(root, patch)
            changed.add(patch.file.split("/", 1)[0])
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", commit.message, date=f"2026-09-0{1 + number}T10:00:00")
    git(root, "tag", "deploy-current")
    if scenario.fault:
        patch = scenario.fault.patches[0]
        truth.file = patch.file
        truth.start_line, truth.end_line = locate(root, patch)
    return sorted(changed)


def fixed_copy(root: Path, scenario: Scenario, destination: Path) -> Path:
    """The known-good version: the deployed workspace with only the fault reverted."""
    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
    shutil.copytree(root, destination, ignore=shutil.ignore_patterns(".git", "__pycache__", "logs", "sentinel_generated"))
    if scenario.fault:
        for patch in scenario.fault.patches:
            apply_patch(destination, patch, reverse=True)
    return destination
