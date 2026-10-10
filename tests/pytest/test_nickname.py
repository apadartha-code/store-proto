"""Features.md §6 — nicknames; §7 recall."""

from __future__ import annotations

import io

from PIL import Image


def _ingest(app) -> str:
    from app.services.upload import ingest_image

    raw = io.BytesIO()
    Image.new("RGB", (4, 4)).save(raw, "PNG")
    return ingest_image(
        "n.png",
        raw.getvalue(),
        {
            "sharing": "public",
            "categories": ["General"],
            "source": "t",
            "license": "Public Domain",
        },
    )


def test_nickname_hash_lookup(app):
    from app.services.nickname import find_images_by_nickname, set_user_nickname

    image_id = _ingest(app)
    set_user_nickname(image_id, "my-nick-label")
    found = find_images_by_nickname("my-nick-label")
    assert image_id in found


def test_nearest_hash_predecessor(app):
    from app.db import db_session
    from app.services.nickname import (
        add_nickname_hash,
        find_images_by_hash,
        find_images_by_nickname,
        nearest_hash_for_target,
    )

    id_low = _ingest(app)
    id_high = _ingest(app)
    with db_session() as conn:
        conn.execute("DELETE FROM nicknames")
    add_nickname_hash(id_low, 0x100000)
    add_nickname_hash(id_high, 0x300000)

    assert nearest_hash_for_target(0x200000) == 0x100000
    assert find_images_by_hash(0x200000) == []
    # 6-char hex: no exact row; falls back to nearest hash 0x100000
    assert find_images_by_nickname("200000") == [id_low]


def test_nearest_hash_wraps_to_max(app):
    from app.db import db_session
    from app.services.nickname import (
        add_nickname_hash,
        find_images_by_nickname,
        nearest_hash_for_target,
    )

    id_low = _ingest(app)
    id_high = _ingest(app)
    with db_session() as conn:
        conn.execute("DELETE FROM nicknames")
    add_nickname_hash(id_low, 0x100000)
    add_nickname_hash(id_high, 0x300000)

    assert nearest_hash_for_target(0x050000) == 0x300000
    assert find_images_by_nickname("050000") == [id_high]
