from __future__ import annotations

import json
import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.config import Config
from app.db import db_session
from app.services.fragments import split_into_fragments
from app.services.nickname import add_random_default_nickname
from app.services.thumbnail import schedule_thumbnail, thumbnail_path

logger = logging.getLogger(__name__)


class UploadValidationError(ValueError):
    pass


def _validate_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    sharing = (meta.get("sharing") or "public").lower()
    category = (meta.get("category") or "general").lower()
    if sharing not in ("public", "shared", "private"):
        raise UploadValidationError("Invalid sharing value")
    if category not in ("general", "adult", "violent"):
        raise UploadValidationError("Invalid category value")

    source = meta.get("source")
    if sharing == "public" and not source:
        raise UploadValidationError("Source is mandatory for public images")
    if sharing == "private":
        source = None

    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    if not isinstance(tags, list):
        raise UploadValidationError("Tags must be a list")

    license_val = meta.get("license")

    return {
        "sharing": sharing,
        "category": category,
        "source": source,
        "tags": tags,
        "license": license_val,
    }


def detect_mime(filename: str, raw: bytes) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    if guessed and guessed.startswith("image/"):
        return guessed
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return guessed or "application/octet-stream"


def ingest_image(
    filename: str,
    raw: bytes,
    meta: dict[str, Any],
) -> str:
    max_bytes = Config.MAX_UPLOAD_KB * 1024
    if len(raw) > max_bytes:
        msg = f"Image exceeds max upload size of {Config.MAX_UPLOAD_KB} KB"
        logger.error("Upload rejected for %s: %s", filename, msg)
        raise UploadValidationError(msg)
    if len(raw) == 0:
        logger.error("Upload rejected for %s: empty file", filename)
        raise UploadValidationError("Empty file")

    try:
        fields = _validate_metadata(meta)
    except UploadValidationError as e:
        logger.error("Upload rejected for %s: %s", filename, e)
        raise

    mime = detect_mime(filename, raw)
    if not mime.startswith("image/"):
        msg = "File is not a recognized image type"
        logger.error("Upload rejected for %s: %s (detected %s)", filename, msg, mime)
        raise UploadValidationError(msg)

    image_id = str(uuid.uuid4())
    upload_time = datetime.now(timezone.utc).isoformat()
    fragments = split_into_fragments(raw, fields["sharing"])

    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO images (
                id, original_name, upload_time, mime_type, image_size,
                sharing, category, tags, source, license
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                image_id,
                filename,
                upload_time,
                mime,
                len(raw),
                fields["sharing"],
                fields["category"],
                json.dumps(fields["tags"]),
                fields["source"],
                fields["license"],
            ),
        )
        for fragment_id, index in fragments:
            conn.execute(
                """
                INSERT INTO fragments (
                    fragment_id, fragment_size_kb, image_id, fragment_index
                ) VALUES (?, ?, ?, ?)
                """,
                (fragment_id, Config.FRAGMENT_SIZE_KB, image_id, index),
            )

    add_random_default_nickname(image_id)
    schedule_thumbnail(image_id)

    thumb = thumbnail_path(image_id)
    logger.info(
        "Ingested image original_name=%s image_id=%s mime_type=%s image_size=%s "
        "upload_time=%s sharing=%s category=%s tags=%s source=%s license=%s "
        "fragment_count=%s thumbnail_path=%s",
        filename,
        image_id,
        mime,
        len(raw),
        upload_time,
        fields["sharing"],
        fields["category"],
        fields["tags"],
        fields["source"],
        fields["license"],
        len(fragments),
        thumb,
    )
    return image_id


def update_image_tags(image_id: str, tags: list[str]) -> None:
    with db_session() as conn:
        row = conn.execute("SELECT id FROM images WHERE id = ?", (image_id,)).fetchone()
        if not row:
            logger.error("Tag update failed: image not found image_id=%s", image_id)
            raise UploadValidationError("Image not found")
        conn.execute(
            "UPDATE images SET tags = ? WHERE id = ?",
            (json.dumps(tags), image_id),
        )
