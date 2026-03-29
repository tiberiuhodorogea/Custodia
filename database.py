import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custodia.db")


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sources (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            path       TEXT NOT NULL UNIQUE,
            label      TEXT NOT NULL,
            enabled    INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS destinations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            path       TEXT NOT NULL UNIQUE,
            label      TEXT NOT NULL,
            enabled    INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS backup_runs (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at    TEXT NOT NULL,
            completed_at  TEXT,
            status        TEXT NOT NULL DEFAULT 'running',
            files_total   INTEGER DEFAULT 0,
            files_copied  INTEGER DEFAULT 0,
            files_skipped INTEGER DEFAULT 0,
            files_failed  INTEGER DEFAULT 0,
            bytes_total   INTEGER DEFAULT 0,
            bytes_copied  INTEGER DEFAULT 0,
            error_message TEXT
        );
        CREATE TABLE IF NOT EXISTS backup_logs (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id    INTEGER,
            timestamp TEXT DEFAULT (datetime('now','localtime')),
            level     TEXT NOT NULL,
            message   TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES backup_runs(id)
        );
    """)
    defaults = {
        "frequency_days": "1",
        "backup_time": "02:00",
        "retention_count": "3",
        "scheduler_enabled": "true",
    }
    for key, value in defaults.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()
    conn.close()


# ── Settings ────────────────────────────────────────────

def get_settings():
    conn = _connect()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def update_settings(data: dict):
    conn = _connect()
    for key, value in data.items():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
    conn.commit()
    conn.close()


# ── Sources ─────────────────────────────────────────────

def get_sources():
    conn = _connect()
    rows = conn.execute(
        "SELECT id, path, label, enabled, created_at FROM sources ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_source(path: str, label: str):
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO sources (path, label) VALUES (?, ?)", (path, label)
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def remove_source(source_id: int):
    conn = _connect()
    conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
    conn.commit()
    conn.close()


def toggle_source(source_id: int, enabled: bool):
    conn = _connect()
    conn.execute(
        "UPDATE sources SET enabled=? WHERE id=?", (int(enabled), source_id)
    )
    conn.commit()
    conn.close()


# ── Destinations ────────────────────────────────────────

def get_destinations():
    conn = _connect()
    rows = conn.execute(
        "SELECT id, path, label, enabled, created_at FROM destinations ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_destination(path: str, label: str):
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO destinations (path, label) VALUES (?, ?)", (path, label)
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def remove_destination(dest_id: int):
    conn = _connect()
    conn.execute("DELETE FROM destinations WHERE id=?", (dest_id,))
    conn.commit()
    conn.close()


def toggle_destination(dest_id: int, enabled: bool):
    conn = _connect()
    conn.execute(
        "UPDATE destinations SET enabled=? WHERE id=?", (int(enabled), dest_id)
    )
    conn.commit()
    conn.close()


# ── Backup runs ─────────────────────────────────────────

def create_run():
    conn = _connect()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "INSERT INTO backup_runs (started_at, status) VALUES (?, 'running')",
        (now,),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id


def update_run(run_id: int, **kwargs):
    conn = _connect()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [run_id]
    conn.execute(f"UPDATE backup_runs SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()


def complete_run(run_id: int, status: str, **kwargs):
    kwargs["status"] = status
    kwargs["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    update_run(run_id, **kwargs)


def get_runs(limit: int = 20):
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM backup_runs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Logs ────────────────────────────────────────────────

def add_log(run_id: int, level: str, message: str):
    conn = _connect()
    conn.execute(
        "INSERT INTO backup_logs (run_id, level, message) VALUES (?, ?, ?)",
        (run_id, level, message),
    )
    conn.commit()
    conn.close()


def get_logs(run_id: int = None, limit: int = 200, offset: int = 0):
    conn = _connect()
    if run_id:
        rows = conn.execute(
            "SELECT * FROM backup_logs WHERE run_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (run_id, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM backup_logs ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
