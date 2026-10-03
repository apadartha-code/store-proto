from __future__ import annotations

import io
import logging
import threading
import urllib.request
from pathlib import Path

from PIL import Image

from app.config import Config
from app.db import db_session
from app.services.backup import backup_database

logger = logging.getLogger(__name__)

_thumb_queue_lock = threading.Lock()
_pending_image_ids: set[str] = set()
_worker_started = False


def thumbnail_path(image_id: str) -> Path:
    return Config.THUMBNAILS_DIR / image_id


def generate_thumbnail(image_id: str, raw: bytes) -> bool:
    path = thumbnail_path(image_id)
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img = img.convert("RGB")
            img.thumbnail((200, 200))
            img.save(path, format="JPEG", quality=85)
        logger.info("Generated thumbnail image_id=%s path=%s", image_id, path)
        return True
    except Exception:
        logger.error(
            "Thumbnail generation failed for image_id=%s path=%s",
            image_id,
            path,
            exc_info=True,
        )
        return False


def _trigger_local_backup() -> None:
    port = Config.LISTEN_PORT
    url = f"http://127.0.0.1:{port}/api/backup"
    try:
        req = urllib.request.Request(url, method="POST", data=b"")
        urllib.request.urlopen(req, timeout=2)
        return
    except Exception:
        pass
    try:
        backup_database()
    except Exception:
        try:
            from app.services.backup import safe_file_copy_backup

            safe_file_copy_backup()
        except Exception:
            pass


def _process_pending() -> None:
    global _pending_image_ids
    processed_any = False
    with _thumb_queue_lock:
        ids = list(_pending_image_ids)
        _pending_image_ids.clear()

    from app.services.fragments import reconstruct_image

    for image_id in ids:
        try:
            raw, _ = reconstruct_image(image_id)
            if generate_thumbnail(image_id, raw):
                processed_any = True
        except Exception:
            logger.error(
                "Thumbnail worker failed for image_id=%s",
                image_id,
                exc_info=True,
            )
            continue

    if processed_any:
        _trigger_local_backup()


def _worker_loop() -> None:
    while True:
        with _thumb_queue_lock:
            has_work = bool(_pending_image_ids)
        if has_work:
            _process_pending()
        else:
            threading.Event().wait(0.5)


def schedule_thumbnail(image_id: str) -> None:
    global _worker_started
    with _thumb_queue_lock:
        _pending_image_ids.add(image_id)
        if not _worker_started:
            _worker_started = True
            t = threading.Thread(target=_worker_loop, daemon=True, name="thumb-worker")
            t.start()


def list_images_missing_thumbnails(limit: int = 50) -> list[str]:
    with db_session() as conn:
        rows = conn.execute("SELECT id FROM images").fetchall()
    missing = []
    for row in rows:
        if not thumbnail_path(row["id"]).exists():
            missing.append(row["id"])
            if len(missing) >= limit:
                break
    return missing
