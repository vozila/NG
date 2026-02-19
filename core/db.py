"""VOZLIA FILE PURPOSE
Purpose: multi-tenant SQLite scaffold with append-only event store APIs.
Hot path: no (durable persistence path; explicit calls only).
Feature flags: none.
Failure mode: deterministic exceptions; caller controls retry/rollback behavior.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = "ops/vozlia_ng.sqlite3"


def _db_path() -> str:
    return os.getenv("VOZ_DB_PATH", DEFAULT_DB_PATH)


def _validate_required(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id TEXT PRIMARY KEY,
            created_ts INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            rid TEXT NOT NULL,
            event_type TEXT NOT NULL,
            ts INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            trace_id TEXT,
            idempotency_key TEXT,
            FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_tenant_ts ON events(tenant_id, ts)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_tenant_type_ts ON events(tenant_id, event_type, ts)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_tenant_rid_ts ON events(tenant_id, rid, ts)"
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_events_tenant_idempotency
        ON events(tenant_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )
    conn.commit()


def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or _db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


def _ensure_tenant(conn: sqlite3.Connection, tenant_id: str) -> None:
    now_ts = int(time.time())
    conn.execute(
        "INSERT OR IGNORE INTO tenants(tenant_id, created_ts) VALUES (?, ?)",
        (tenant_id, now_ts),
    )


def emit_event(
    tenant_id: str,
    rid: str,
    event_type: str,
    payload_dict: dict[str, Any],
    trace_id: str | None = None,
    idempotency_key: str | None = None,
) -> str:
    _validate_required(tenant_id, "tenant_id")
    _validate_required(rid, "rid")
    _validate_required(event_type, "event_type")
    if not isinstance(payload_dict, dict):
        raise ValueError("payload_dict must be a dict")

    with get_conn() as conn:
        _ensure_tenant(conn, tenant_id)

        if idempotency_key:
            row = conn.execute(
                """
                SELECT event_id
                FROM events
                WHERE tenant_id = ? AND idempotency_key = ?
                LIMIT 1
                """,
                (tenant_id, idempotency_key),
            ).fetchone()
            if row is not None:
                return str(row["event_id"])

        event_id = str(uuid.uuid4())
        now_ts = int(time.time())
        payload_json = json.dumps(payload_dict, sort_keys=True, separators=(",", ":"))
        try:
            conn.execute(
                """
                INSERT INTO events(
                    event_id, tenant_id, rid, event_type, ts, payload_json, trace_id, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    tenant_id,
                    rid,
                    event_type,
                    now_ts,
                    payload_json,
                    trace_id,
                    idempotency_key,
                ),
            )
            conn.commit()
            return event_id
        except sqlite3.IntegrityError:
            if not idempotency_key:
                raise
            row = conn.execute(
                """
                SELECT event_id
                FROM events
                WHERE tenant_id = ? AND idempotency_key = ?
                LIMIT 1
                """,
                (tenant_id, idempotency_key),
            ).fetchone()
            if row is None:
                raise
            return str(row["event_id"])


def query_events(
    tenant_id: str,
    event_type: str | None = None,
    since_ts: int | None = None,
    until_ts: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    _validate_required(tenant_id, "tenant_id")
    safe_limit = max(1, min(int(limit), 1000))

    query = """
        SELECT event_id, tenant_id, rid, event_type, ts, payload_json, trace_id, idempotency_key
        FROM events
        WHERE tenant_id = ?
    """
    params: list[Any] = [tenant_id]

    if event_type is not None:
        query += " AND event_type = ?"
        params.append(event_type)
    if since_ts is not None:
        query += " AND ts >= ?"
        params.append(int(since_ts))
    if until_ts is not None:
        query += " AND ts <= ?"
        params.append(int(until_ts))

    query += " ORDER BY ts ASC, event_id ASC LIMIT ?"
    params.append(safe_limit)

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "event_id": str(row["event_id"]),
                "tenant_id": str(row["tenant_id"]),
                "rid": str(row["rid"]),
                "event_type": str(row["event_type"]),
                "ts": int(row["ts"]),
                "payload": json.loads(str(row["payload_json"])),
                "trace_id": row["trace_id"],
                "idempotency_key": row["idempotency_key"],
            }
        )
    return out


def query_events_for_rid(
    tenant_id: str,
    rid: str,
    event_type: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    _validate_required(tenant_id, "tenant_id")
    _validate_required(rid, "rid")
    safe_limit = max(1, min(int(limit), 5000))

    query = """
        SELECT event_id, tenant_id, rid, event_type, ts, payload_json, trace_id, idempotency_key
        FROM events
        WHERE tenant_id = ? AND rid = ?
    """
    params: list[Any] = [tenant_id, rid]

    if event_type is not None:
        query += " AND event_type = ?"
        params.append(event_type)

    query += " ORDER BY ts ASC, event_id ASC LIMIT ?"
    params.append(safe_limit)

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "event_id": str(row["event_id"]),
                "tenant_id": str(row["tenant_id"]),
                "rid": str(row["rid"]),
                "event_type": str(row["event_type"]),
                "ts": int(row["ts"]),
                "payload": json.loads(str(row["payload_json"])),
                "trace_id": row["trace_id"],
                "idempotency_key": row["idempotency_key"],
            }
        )
    return out
