"""SQLite persistence: services, deployments, incidents and the audit trail."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS services (
  name TEXT PRIMARY KEY, source TEXT, kind TEXT, package TEXT, module TEXT, port INTEGER,
  health_path TEXT, metrics_path TEXT, mem_limit_mb INTEGER, cpu_limit REAL, owner TEXT,
  auto_rollback INTEGER, created_at REAL, desired TEXT DEFAULT 'running');
CREATE TABLE IF NOT EXISTS deployments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, service TEXT, commit_sha TEXT, message TEXT, image TEXT, trig TEXT,
  status TEXT, last_good INTEGER DEFAULT 0, instance TEXT, url TEXT, created_at REAL, healthy_at REAL,
  ended_at REAL, detail TEXT);
CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY AUTOINCREMENT, service TEXT, deployment_id INTEGER, kind TEXT, status TEXT,
  opened_at REAL, closed_at REAL, summary TEXT, signals TEXT, diagnosis TEXT, patch TEXT, auto_action TEXT);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, actor TEXT, service TEXT, incident_id INTEGER, action TEXT, detail TEXT);
"""
OPEN_STATES = ("open", "investigating", "diagnosed", "rolled_back", "needs_attention")
BOOLS = {"auto_rollback", "last_good"}
JSONS = {"signals", "diagnosis", "detail"}


def _row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for key in BOOLS & out.keys():
        out[key] = bool(out[key])
    for key in JSONS & out.keys():
        out[key] = json.loads(out[key]) if out[key] else ({} if key != "signals" else [])
    if "commit_sha" in out:
        out["commit"] = out.pop("commit_sha")
    if "trig" in out:
        out["trigger"] = out.pop("trig")
    return out


class Store:
    def __init__(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._db.executescript(SCHEMA)

    def _q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [_row(r) for r in self._db.execute(sql, args).fetchall()]

    def _x(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            return self._db.execute(sql, args).lastrowid

    def _set(self, table: str, key: str, value, fields: dict) -> None:
        if not fields:
            return
        mapped = {("commit_sha" if k == "commit" else "trig" if k == "trigger" else k): v for k, v in fields.items()}
        cols = ", ".join(f"{k} = ?" for k in mapped)
        vals = tuple(json.dumps(v) if k in JSONS else int(v) if k in BOOLS else v for k, v in mapped.items())
        self._x(f"UPDATE {table} SET {cols} WHERE {key} = ?", (*vals, value))

    # services ------------------------------------------------------------------------------
    def add_service(self, svc: dict) -> None:
        cols = ("name", "source", "kind", "package", "module", "port", "health_path", "metrics_path", "mem_limit_mb", "cpu_limit",
                "owner", "auto_rollback", "created_at")
        values = {**svc, "created_at": time.time(), "auto_rollback": int(svc.get("auto_rollback", True))}
        self._x(f"INSERT INTO services ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", tuple(values.get(c) for c in cols))

    def get_service(self, name: str) -> dict | None:
        rows = self._q("SELECT * FROM services WHERE name = ?", (name,))
        return rows[0] if rows else None

    def list_services(self) -> list[dict]:
        return self._q("SELECT * FROM services ORDER BY created_at, name")

    def update_service(self, name: str, **fields) -> None:
        self._set("services", "name", name, fields)

    def delete_service(self, name: str) -> None:
        self._x("DELETE FROM services WHERE name = ?", (name,))

    # deployments ---------------------------------------------------------------------------
    def add_deployment(self, service: str, commit: str, message: str, image: str | None, trigger: str, status: str = "building") -> int:
        return self._x("INSERT INTO deployments (service, commit_sha, message, image, trig, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (service, commit, message, image, trigger, status, time.time()))

    def update_deployment(self, dep_id: int, **fields) -> None:
        self._set("deployments", "id", dep_id, fields)

    def get_deployment(self, dep_id: int) -> dict | None:
        rows = self._q("SELECT * FROM deployments WHERE id = ?", (dep_id,))
        return rows[0] if rows else None

    def deployments(self, service: str, limit: int = 50) -> list[dict]:
        return self._q("SELECT * FROM deployments WHERE service = ? ORDER BY id DESC LIMIT ?", (service, limit))

    def current_deployment(self, service: str) -> dict | None:
        rows = self._q("SELECT * FROM deployments WHERE service = ? AND status IN ('healthy', 'starting') ORDER BY id DESC LIMIT 1", (service,))
        return rows[0] if rows else None

    def last_good(self, service: str) -> dict | None:
        rows = self._q("SELECT * FROM deployments WHERE service = ? AND last_good = 1 ORDER BY id DESC LIMIT 1", (service,))
        return rows[0] if rows else None

    def set_last_good(self, dep_id: int) -> None:
        dep = self.get_deployment(dep_id)
        with self._lock:
            self._db.execute("UPDATE deployments SET last_good = 0 WHERE service = ?", (dep["service"],))
            self._db.execute("UPDATE deployments SET last_good = 1 WHERE id = ?", (dep_id,))

    # incidents -----------------------------------------------------------------------------
    def open_incident(self, service: str, deployment_id: int | None, kind: str, summary: str, signals: list) -> int:
        return self._x("INSERT INTO incidents (service, deployment_id, kind, status, opened_at, summary, signals) VALUES (?, ?, ?, 'open', ?, ?, ?)",
                       (service, deployment_id, kind, time.time(), summary, json.dumps(signals)))

    def update_incident(self, inc_id: int, **fields) -> None:
        if fields.get("status") in ("resolved", "dismissed") and "closed_at" not in fields:
            fields["closed_at"] = time.time()
        self._set("incidents", "id", inc_id, fields)

    def get_incident(self, inc_id: int) -> dict | None:
        rows = self._q("SELECT * FROM incidents WHERE id = ?", (inc_id,))
        return rows[0] if rows else None

    def incidents(self, service: str | None = None, limit: int = 100) -> list[dict]:
        if service:
            return self._q("SELECT * FROM incidents WHERE service = ? ORDER BY id DESC LIMIT ?", (service, limit))
        return self._q("SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (limit,))

    def open_incident_for(self, service: str) -> dict | None:
        marks = ", ".join("?" * len(OPEN_STATES))
        rows = self._q(f"SELECT * FROM incidents WHERE service = ? AND status IN ({marks}) ORDER BY id DESC LIMIT 1", (service, *OPEN_STATES))
        return rows[0] if rows else None

    # audit ---------------------------------------------------------------------------------
    def audit(self, actor: str, action: str, service: str | None = None, incident_id: int | None = None, **detail) -> dict:
        at = time.time()
        row_id = self._x("INSERT INTO audit (at, actor, service, incident_id, action, detail) VALUES (?, ?, ?, ?, ?, ?)",
                         (at, actor, service, incident_id, action, json.dumps(detail, default=str)))
        return {"id": row_id, "at": at, "actor": actor, "service": service, "incident_id": incident_id, "action": action, "detail": detail}

    def audit_events(self, limit: int = 100, service: str | None = None, incident_id: int | None = None) -> list[dict]:
        where, args = [], []
        if service:
            where.append("service = ?")
            args.append(service)
        if incident_id:
            where.append("incident_id = ?")
            args.append(incident_id)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        return self._q(f"SELECT * FROM audit {clause} ORDER BY id DESC LIMIT ?", (*args, limit))
