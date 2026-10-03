from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from app.config import Config

_write_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(Config.DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def write_lock() -> Iterator[None]:
    """Block concurrent writers (e.g. backup) without holding an open transaction."""
    with _write_lock:
        yield


@contextmanager
def exclusive_write() -> Iterator[sqlite3.Connection]:
    """Transactional write under the process-wide write lock."""
    with _write_lock:
        conn = get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    Config.ensure_dirs()
    with db_session() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS images (
                id TEXT PRIMARY KEY,
                original_name TEXT NOT NULL,
                upload_time TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                image_size INTEGER NOT NULL,
                sharing TEXT NOT NULL CHECK (sharing IN ('public', 'shared', 'private')),
                category TEXT NOT NULL CHECK (category IN ('general', 'adult', 'violent')),
                tags TEXT,
                source TEXT,
                license TEXT
            );

            CREATE TABLE IF NOT EXISTS fragments (
                fragment_id TEXT NOT NULL,
                fragment_size_kb INTEGER NOT NULL,
                image_id TEXT NOT NULL,
                fragment_index INTEGER NOT NULL,
                PRIMARY KEY (image_id, fragment_index),
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_fragments_fragment_id
                ON fragments(fragment_id);

            CREATE TABLE IF NOT EXISTS nicknames (
                nickname TEXT PRIMARY KEY,
                image_id TEXT NOT NULL,
                hash INTEGER NOT NULL,
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_nicknames_hash ON nicknames(hash);
            CREATE INDEX IF NOT EXISTS idx_nicknames_image ON nicknames(image_id);
            CREATE INDEX IF NOT EXISTS idx_images_upload ON images(upload_time DESC);
            """
        )


def row_to_image(row: sqlite3.Row) -> dict[str, Any]:
    tags = json.loads(row["tags"]) if row["tags"] else []
    return {
        "id": row["id"],
        "original_name": row["original_name"],
        "upload_time": row["upload_time"],
        "mime_type": row["mime_type"],
        "image_size": row["image_size"],
        "sharing": row["sharing"],
        "category": row["category"],
        "tags": tags,
        "source": row["source"],
        "license": row["license"],
    }
