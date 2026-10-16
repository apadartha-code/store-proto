from __future__ import annotations

import json
from typing import Iterable

from app.db import db_session
from app.services.errors import UploadValidationError
from app.services.upload import update_image_tags


def merge_tags_into_image(image_id: str, tags_to_add: Iterable[str]) -> list[str]:
    """Add tags not already present (case-insensitive); return merged tag list."""
    with db_session() as conn:
        row = conn.execute(
            "SELECT tags FROM images WHERE id = ?", (image_id,)
        ).fetchone()
        if not row:
            raise UploadValidationError("Image not found")
        existing: list[str] = json.loads(row["tags"]) if row["tags"] else []

    seen = {t.lower() for t in existing}
    merged = list(existing)
    for raw in tags_to_add:
        tag = (raw or "").strip()
        if not tag:
            continue
        if tag.lower() in seen:
            continue
        merged.append(tag)
        seen.add(tag.lower())

    update_image_tags(image_id, merged)
    return merged
