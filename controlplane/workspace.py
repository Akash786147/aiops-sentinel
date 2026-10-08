"""A monitored service's source: a git working copy Sentinel deploys from.

History is never rewritten: a rollback or a lab reset restores an older tree into the working copy and commits it,
so every running version is a commit and every change can be diffed and investigated.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "logs", ".git", "sentinel_generated")
GITIGNORE = "__pycache__/\n*.pyc\nlogs/\nsentinel_generated/\n"
ENV = {"GIT_AUTHOR_NAME": "sentinel", "GIT_AUTHOR_EMAIL": "sentinel@localhost", "GIT_COMMITTER_NAME": "sentinel",
       "GIT_COMMITTER_EMAIL": "sentinel@localhost"}
READABLE = {".py", ".txt", ".md", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".html", ".js", ".css", ""}


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def git(self, *args: str, check: bool = True, author: str | None = None) -> str:
        env = {**os.environ, **ENV}
        if author:
            env.update(GIT_AUTHOR_NAME=author)
        done = subprocess.run(["git", *args], cwd=self.root, env=env, capture_output=True, text=True, check=False)
        if check and done.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
        return done.stdout

    def exists(self) -> bool:
        return (self.root / ".git").exists()

    def init_from_dir(self, source: Path, message: str = "Initial import") -> str:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        shutil.copytree(source, self.root, ignore=IGNORE)
        (self.root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.head()

    def clone(self, url: str, branch: str | None = None) -> str:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        self.root.parent.mkdir(parents=True, exist_ok=True)
        args = ["git", "clone", "-q", *(["--branch", branch] if branch else []), url, str(self.root)]
        done = subprocess.run(args, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise RuntimeError(f"git clone failed: {done.stderr.strip()}")
        ignore = self.root / ".gitignore"
        current = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
        if "sentinel_generated/" not in current:
            ignore.write_text(current + ("\n" if current and not current.endswith("\n") else "") + GITIGNORE, encoding="utf-8")
            self.commit("Sentinel: ignore runtime files")
        return self.head()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def subject(self, sha: str) -> str:
        return self.git("log", "-1", "--format=%s", sha).strip()

    def dirty(self) -> bool:
        return bool(self.git("status", "--porcelain").strip())

    def changed_files(self) -> list[str]:
        return [line[3:].strip() for line in self.git("status", "--porcelain").splitlines() if line.strip()]

    def commit(self, message: str, author: str | None = None) -> str:
        if self.dirty():
            self.git("add", "-A")
            self.git("commit", "-q", "-m", message, author=author)
        return self.head()

    def diff(self, a: str, b: str | None = None) -> str:
        return self.git("diff", a, *( [b] if b else []))

    def working_diff(self) -> str:
        self.git("add", "-A", "-N")
        return self.git("diff", "HEAD")

    def restore(self, sha: str) -> None:
        """Make the working tree equal to ``sha`` without moving HEAD (the change shows as uncommitted)."""
        self.git("read-tree", "--reset", "-u", sha)
        self.git("clean", "-fdq", "-e", "logs", "-e", "sentinel_generated")

    def discard(self) -> None:
        self.git("reset", "-q", "--hard", "HEAD")
        self.git("clean", "-fdq", "-e", "logs", "-e", "sentinel_generated")

    def tag(self, name: str, sha: str) -> None:
        self.git("tag", "-f", name, sha)

    def export(self, sha: str, destination: Path) -> Path:
        """The tree of ``sha`` as plain files (known-good copy for tests, rebuilds)."""
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        destination.mkdir(parents=True)
        data = subprocess.run(["git", "archive", "--format=zip", sha], cwd=self.root, capture_output=True, check=True).stdout
        zipfile.ZipFile(io.BytesIO(data)).extractall(destination)
        return destination

    def files(self) -> list[str]:
        tracked = self.git("ls-files", "--cached", "--others", "--exclude-standard").splitlines()
        return sorted(f for f in tracked if f and Path(f).suffix in READABLE)

    def _safe(self, rel: str) -> Path:
        root = self.root.resolve()
        target = (root / rel).resolve()
        if root not in target.parents or ".git" in target.relative_to(root).parts:
            raise ValueError("path is outside the service workspace")
        return target

    def read(self, rel: str) -> str:
        target = self._safe(rel)
        if not target.is_file():
            raise FileNotFoundError(rel)
        return target.read_text(encoding="utf-8", errors="replace")

    def read_at(self, sha: str, rel: str) -> str:
        """A file as it was in commit ``sha`` (incident pages show the faulty version, not today's)."""
        self._safe(rel)
        if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
            raise ValueError("invalid commit")
        done = subprocess.run(["git", "show", f"{sha}:{rel}"], cwd=self.root, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise FileNotFoundError(rel)
        return done.stdout

    def write(self, rel: str, text: str) -> None:
        target = self._safe(rel)
        if target.suffix not in READABLE:
            raise ValueError("this file type cannot be edited here")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
