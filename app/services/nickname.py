from __future__ import annotations

import hashlib
import secrets
from typing import Optional

from app.db import db_session

_HASH_MASK = 0xFFFFFF


def nickname_hash_from_text(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:3], "big") & _HASH_MASK


def random_nickname_hash() -> int:
    return secrets.randbelow(_HASH_MASK + 1)


def hash_to_display(h: int) -> str:
    return f"{h & _HASH_MASK:06x}"


def parse_hash_input(value: str) -> Optional[int]:
    v = value.strip().lower()
    if len(v) == 6 and all(c in "0123456789abcdef" for c in v):
        return int(v, 16) & _HASH_MASK
    return nickname_hash_from_text(value)


def add_nickname_hash(image_id: str, hash_value: int) -> None:
    h = hash_value & _HASH_MASK
    with db_session() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO nicknames (hash, image_id) VALUES (?, ?)",
            (h, image_id),
        )


def add_random_default_nickname(image_id: str) -> None:
    add_nickname_hash(image_id, random_nickname_hash())


def set_user_nickname(image_id: str, description: str) -> int:
    h = nickname_hash_from_text(description)
    with db_session() as conn:
        conn.execute("DELETE FROM nicknames WHERE image_id = ?", (image_id,))
        conn.execute(
            "INSERT INTO nicknames (hash, image_id) VALUES (?, ?)",
            (h, image_id),
        )
    return h


def find_images_by_hash(target: int) -> list[str]:
    h = target & _HASH_MASK
    with db_session() as conn:
        rows = conn.execute(
            "SELECT image_id FROM nicknames WHERE hash = ? ORDER BY image_id",
            (h,),
        ).fetchall()
    return [r["image_id"] for r in rows]


def nearest_hash_for_target(target: int) -> Optional[int]:
    """Largest stored hash <= target, or wrap to max hash if none (Phase 1 ordering)."""
    h = target & _HASH_MASK
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT hash FROM nicknames
            WHERE hash <= ?
            ORDER BY hash DESC
            LIMIT 1
            """,
            (h,),
        ).fetchone()
        if row:
            return int(row["hash"])
        row = conn.execute(
            "SELECT hash FROM nicknames ORDER BY hash DESC LIMIT 1"
        ).fetchone()
        return int(row["hash"]) if row else None


def find_images_by_nickname(nickname_input: str) -> list[str]:
    target = parse_hash_input(nickname_input)
    if target is None:
        return []
    exact = find_images_by_hash(target)
    if exact:
        return exact
    nearest = nearest_hash_for_target(target)
    if nearest is None:
        return []
    return find_images_by_hash(nearest)


def list_nickname_hashes_for_image(image_id: str) -> list[int]:
    with db_session() as conn:
        rows = conn.execute(
            "SELECT hash FROM nicknames WHERE image_id = ? ORDER BY hash",
            (image_id,),
        ).fetchall()
    return [int(r["hash"]) for r in rows]
