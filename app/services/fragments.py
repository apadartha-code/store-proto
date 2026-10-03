from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

from app.config import Config
from app.db import db_session

logger = logging.getLogger(__name__)


def fragment_bytes_size() -> int:
    return Config.FRAGMENT_SIZE_KB * 1024


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fragment_path(folder: Path, fragment_id: str) -> Path:
    return folder / fragment_id


def store_fragment(data: bytes, sharing: str) -> str:
    """Store fragment file; return fragment_id (SHA-256 hex)."""
    fragment_id = sha256_hex(data)
    public_path = _fragment_path(Config.FRAGMENTS_PUBLIC_DIR, fragment_id)
    user_path = _fragment_path(Config.FRAGMENTS_USER_DIR, fragment_id)

    if public_path.exists():
        logger.debug("Fragment already in public store: %s", fragment_id)
        return fragment_id

    if sharing == "public":
        if user_path.exists():
            shutil.move(str(user_path), str(public_path))
            logger.debug("Moved fragment to public store: %s", fragment_id)
        else:
            public_path.write_bytes(data)
            logger.debug("Wrote fragment to public store: %s", fragment_id)
    else:
        if not user_path.exists():
            user_path.write_bytes(data)
            logger.debug("Wrote fragment to user store: %s", fragment_id)
        else:
            logger.debug("Fragment already in user store: %s", fragment_id)

    return fragment_id


def split_into_fragments(raw: bytes, sharing: str) -> list[tuple[str, int]]:
    chunk_size = fragment_bytes_size()
    padded_len = ((len(raw) + chunk_size - 1) // chunk_size) * chunk_size
    padded = raw + (b"\x00" * (padded_len - len(raw)))

    result: list[tuple[str, int]] = []
    index = 0
    for offset in range(0, padded_len, chunk_size):
        chunk = padded[offset : offset + chunk_size]
        fragment_id = store_fragment(chunk, sharing)
        result.append((fragment_id, index))
        index += 1
    return result


def _resolve_fragment_path(fragment_id: str):
    public_path = _fragment_path(Config.FRAGMENTS_PUBLIC_DIR, fragment_id)
    if public_path.exists():
        return public_path
    user_path = _fragment_path(Config.FRAGMENTS_USER_DIR, fragment_id)
    if user_path.exists():
        return user_path
    return None


def reconstruct_image(image_id: str) -> tuple[bytes, str]:
    with db_session() as conn:
        img = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
        if not img:
            raise FileNotFoundError("Image not found")
        rows = conn.execute(
            """
            SELECT fragment_id, fragment_index
            FROM fragments
            WHERE image_id = ?
            ORDER BY fragment_index ASC
            """,
            (image_id,),
        ).fetchall()

    if not rows:
        raise FileNotFoundError("No fragments for image")

    parts: list[bytes] = []
    for row in rows:
        path = _resolve_fragment_path(row["fragment_id"])
        if path is None:
            raise FileNotFoundError(f"Fragment missing: {row['fragment_id']}")
        parts.append(path.read_bytes())

    data = b"".join(parts)
    return data[: img["image_size"]], img["mime_type"]
