from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from app.config import Config
from app.services.dictionary import get_dictionary

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
    with _write_lock:
        yield


@contextmanager
def exclusive_write() -> Iterator[sqlite3.Connection]:
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


def _category_ids_for_image(conn: sqlite3.Connection, image_id: str) -> list[int]:
    rows = conn.execute(
        "SELECT category_id FROM image_categories WHERE image_id = ? ORDER BY category_id",
        (image_id,),
    ).fetchall()
    return [int(r["category_id"]) for r in rows]


def row_to_image(row: sqlite3.Row, conn: Optional[sqlite3.Connection] = None) -> dict[str, Any]:
    dd = get_dictionary()
    tags = json.loads(row["tags"]) if row["tags"] else []
    license_id = int(row["license_id"])
    lic = dd.license_by_id(license_id)

    category_ids: list[int]
    if conn is not None:
        category_ids = _category_ids_for_image(conn, row["id"])
    else:
        with db_session() as c:
            category_ids = _category_ids_for_image(c, row["id"])

    categories = []
    for cid in category_ids:
        cat = dd.category_by_id(cid)
        if cat:
            categories.append(cat.key)

    return {
        "id": row["id"],
        "original_name": row["original_name"],
        "upload_time": row["upload_time"],
        "mime_type": row["mime_type"],
        "image_size": row["image_size"],
        "sharing": row["sharing"],
        "category_ids": category_ids,
        "categories": categories,
        "tags": tags,
        "source": row["source"],
        "license_id": license_id,
        "license": lic.key if lic else None,
        "content_checksum": row["content_checksum"],
    }


def _migrate_images_content_checksum(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(images)")}
    if "content_checksum" not in cols:
        conn.execute("ALTER TABLE images ADD COLUMN content_checksum TEXT")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_images_content_checksum_size
        ON images(content_checksum, image_size)
        """
    )


def init_db() -> None:
    Config.ensure_dirs()
    get_dictionary()
    with db_session() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS images (
                id TEXT PRIMARY KEY,
                original_name TEXT NOT NULL,
                upload_time TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                image_size INTEGER NOT NULL,
                content_checksum TEXT NOT NULL,
                sharing TEXT NOT NULL CHECK (sharing IN ('public', 'shared', 'private')),
                tags TEXT,
                source TEXT,
                license_id INTEGER NOT NULL,
                UNIQUE (content_checksum, image_size)
            );

            CREATE TABLE IF NOT EXISTS image_categories (
                image_id TEXT NOT NULL,
                category_id INTEGER NOT NULL,
                PRIMARY KEY (image_id, category_id),
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_image_categories_cat
                ON image_categories(category_id);

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
                hash INTEGER NOT NULL,
                image_id TEXT NOT NULL,
                PRIMARY KEY (hash, image_id),
                FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_nicknames_hash ON nicknames(hash);
            CREATE INDEX IF NOT EXISTS idx_nicknames_image ON nicknames(image_id);
            CREATE INDEX IF NOT EXISTS idx_images_upload ON images(upload_time DESC);
            """
        )
        _migrate_images_content_checksum(conn)
