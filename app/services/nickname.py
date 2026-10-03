from __future__ import annotations

import hashlib
import secrets
import string
import struct
from typing import Optional

from app.db import db_session


def md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def nickname_hash_from_md5(md5_hex_str: str) -> int:
    hex16 = md5_hex_str[:16].lower()
    return struct.unpack(">q", bytes.fromhex(hex16))[0]


def nickname_hash_from_text(text: str) -> int:
    return nickname_hash_from_md5(md5_hex(text))


def random_nickname_text(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def try_add_nickname(image_id: str, description: str) -> Optional[str]:
    nick_hex = md5_hex(description)
    h = nickname_hash_from_md5(nick_hex)
    with db_session() as conn:
        try:
            conn.execute(
                "INSERT INTO nicknames (nickname, image_id, hash) VALUES (?, ?, ?)",
                (nick_hex, image_id, h),
            )
            return nick_hex
        except Exception:
            return None


def add_random_default_nickname(image_id: str) -> None:
    for _ in range(5):
        text = random_nickname_text()
        if try_add_nickname(image_id, text):
            return


def find_nearest_image_id(nickname_input: str) -> Optional[str]:
    """Match exact MD5 nickname or nearest by hash ordering."""
    candidate = nickname_input.strip().lower()
    if len(candidate) != 32 or not all(c in "0123456789abcdef" for c in candidate):
        candidate = md5_hex(nickname_input)

    target_hash = nickname_hash_from_md5(candidate)

    with db_session() as conn:
        row = conn.execute(
            "SELECT image_id FROM nicknames WHERE nickname = ?", (candidate,)
        ).fetchone()
        if row:
            return row["image_id"]

        row = conn.execute(
            """
            SELECT image_id FROM nicknames
            WHERE hash <= ?
            ORDER BY hash DESC
            LIMIT 1
            """,
            (target_hash,),
        ).fetchone()
        if row:
            return row["image_id"]

        row = conn.execute(
            "SELECT image_id FROM nicknames ORDER BY hash DESC LIMIT 1"
        ).fetchone()
        return row["image_id"] if row else None


def list_nicknames_for_image(image_id: str) -> list[str]:
    with db_session() as conn:
        rows = conn.execute(
            "SELECT nickname FROM nicknames WHERE image_id = ? ORDER BY nickname",
            (image_id,),
        ).fetchall()
    return [r["nickname"] for r in rows]
