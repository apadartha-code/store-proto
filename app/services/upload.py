from __future__ import annotations

import json
import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import Config
from app.db import db_session
from app.services.categories import resolve_category_keys, set_image_categories
from app.services.dictionary import get_dictionary
from app.services.errors import UploadValidationError
from app.services.fragments import split_into_fragments
from app.services.nickname import add_random_default_nickname
from app.services.thumbnail import schedule_thumbnail, thumbnail_path

logger = logging.getLogger(__name__)


def validate_batch_limits(file_count: int, total_bytes: int) -> None:
    if file_count > Config.MAX_UPLOAD_FILE_COUNT:
        raise UploadValidationError(
            f"Too many files (max {Config.MAX_UPLOAD_FILE_COUNT})"
        )
    if total_bytes > Config.MAX_UPLOAD_TOTAL_BYTES:
        raise UploadValidationError(
            f"Combined upload size exceeds {Config.MAX_UPLOAD_TOTAL_BYTES} bytes"
        )


def _validate_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    sharing = (meta.get("sharing") or "public").lower()
    if sharing not in ("public", "shared", "private"):
        raise UploadValidationError("Invalid sharing value")

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

    raw_categories = meta.get("categories") or meta.get("category") or ["General"]
    if isinstance(raw_categories, str):
        raw_categories = [c.strip() for c in raw_categories.split(",") if c.strip()]
    category_ids = resolve_category_keys(raw_categories)

    dd = get_dictionary()
    license_key = meta.get("license") or dd.default_license_key_for_sharing(sharing)
    lic = None
    for lk in dd.license_keys():
        if lk.lower() == str(license_key).lower():
            lic = dd.license_by_key(lk)
            break
    if not lic:
        raise UploadValidationError("Invalid license value")
    if not dd.validate_license_for_sharing(lic.key, sharing):
        raise UploadValidationError(
            f"License {lic.key} is not valid for sharing {sharing}"
        )

    return {
        "sharing": sharing,
        "category_ids": category_ids,
        "source": source,
        "tags": tags,
        "license_id": lic.id,
        "license_key": lic.key,
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
                sharing, tags, source, license_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                image_id,
                filename,
                upload_time,
                mime,
                len(raw),
                fields["sharing"],
                json.dumps(fields["tags"]),
                fields["source"],
                fields["license_id"],
            ),
        )
        for cid in fields["category_ids"]:
            conn.execute(
                "INSERT INTO image_categories (image_id, category_id) VALUES (?, ?)",
                (image_id, cid),
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
        "upload_time=%s sharing=%s category_ids=%s tags=%s source=%s license_id=%s "
        "fragment_count=%s thumbnail_path=%s",
        filename,
        image_id,
        mime,
        len(raw),
        upload_time,
        fields["sharing"],
        fields["category_ids"],
        fields["tags"],
        fields["source"],
        fields["license_id"],
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


def update_image_license(image_id: str, license_key: str, sharing: str) -> None:
    dd = get_dictionary()
    lic = None
    for lk in dd.license_keys():
        if lk.lower() == license_key.lower():
            lic = dd.license_by_key(lk)
            break
    if not lic or not dd.validate_license_for_sharing(lic.key, sharing):
        raise UploadValidationError("Invalid license for image sharing")
    with db_session() as conn:
        row = conn.execute("SELECT id FROM images WHERE id = ?", (image_id,)).fetchone()
        if not row:
            raise UploadValidationError("Image not found")
        conn.execute(
            "UPDATE images SET license_id = ? WHERE id = ?",
            (lic.id, image_id),
        )
