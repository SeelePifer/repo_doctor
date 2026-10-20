import sqlite3
import threading
from pathlib import Path

_locks: dict[str, threading.Lock] = {}
_lock_guard = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  language TEXT NOT NULL,
  sha TEXT NOT NULL,
  line_count INTEGER NOT NULL,
  text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS symbols (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  signature TEXT NOT NULL,
  FOREIGN KEY(file_id) REFERENCES files(id)
);

CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL,
  module TEXT NOT NULL,
  imported_name TEXT NOT NULL,
  local_name TEXT NOT NULL,
  line INTEGER NOT NULL,
  FOREIGN KEY(file_id) REFERENCES files(id)
);

CREATE TABLE IF NOT EXISTS entry_points (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL,
  kind TEXT NOT NULL,
  detail TEXT NOT NULL,
  line INTEGER NOT NULL,
  FOREIGN KEY(file_id) REFERENCES files(id)
);

CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL,
  start_line INTEGER NOT NULL,
  end_line INTEGER NOT NULL,
  text TEXT NOT NULL,
  FOREIGN KEY(file_id) REFERENCES files(id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  path,
  text,
  symbol_names
);

CREATE TABLE IF NOT EXISTS embeddings (
  chunk_id INTEGER PRIMARY KEY,
  vector BLOB NOT NULL,
  FOREIGN KEY(chunk_id) REFERENCES chunks(id)
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  prompt TEXT NOT NULL,
  answer_json TEXT,
  grounding_json TEXT,
  plan_json TEXT,
  diff TEXT,
  verify_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tool_events (
  id INTEGER PRIMARY KEY,
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  tool TEXT NOT NULL,
  args_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_imports_imported ON imports(imported_name);
CREATE INDEX IF NOT EXISTS idx_imports_local ON imports(local_name);
"""


def connection_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _lock_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)
    connection.commit()


def reset_index_content(path: Path) -> sqlite3.Connection:
    connection = connect(path)
    init_db(connection)
    connection.execute("PRAGMA foreign_keys = OFF")
    for table in ("embeddings", "chunks_fts", "chunks", "symbols", "imports", "entry_points", "files"):
        connection.execute(f"DELETE FROM {table}")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.commit()
    return connection


def set_meta(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    return str(row["value"])
