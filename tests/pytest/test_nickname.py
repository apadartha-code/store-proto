"""Features.md §1 — nicknames; §5 recall nearest match."""

from __future__ import annotations

import io

from PIL import Image


def test_exact_nickname_match(app):
    from app.services.nickname import find_nearest_image_id, try_add_nickname
    from app.services.upload import ingest_image

    raw = io.BytesIO()
    Image.new("RGB", (4, 4)).save(raw, "PNG")
    image_id = ingest_image(
        "n.png",
        raw.getvalue(),
        {"sharing": "public", "category": "general", "source": "t"},
    )
    try_add_nickname(image_id, "my-nick-label")
    assert find_nearest_image_id("my-nick-label") == image_id
