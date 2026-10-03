from __future__ import annotations

import io
import logging
import re
import urllib.parse

from flask import send_file

from app.services.fragments import reconstruct_image
from app.services.otp import resolve_image_url_from_otp

logger = logging.getLogger(__name__)

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)


def image_id_from_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or url
    match = UUID_RE.search(path)
    return match.group(0).lower() if match else None


def send_image_download(url: str):
    image_id = image_id_from_url(url)
    if not image_id:
        return None, ("Could not resolve image id from url", 400)

    try:
        raw, mime = reconstruct_image(image_id)
    except FileNotFoundError:
        logger.error("Image download failed: image not found for url=%s", url)
        return None, ("Image not found", 404)

    return send_file(
        io.BytesIO(raw),
        mimetype=mime,
        as_attachment=True,
        download_name=f"{image_id}.bin",
    ), None


def resolve_download_url(
    *,
    url: str | None = None,
    otp: str | None = None,
    id_b64: str | None = None,
) -> tuple[str | None, tuple[str, int] | None]:
    if otp:
        if not id_b64:
            return None, ("id is required when using otp", 400)
        resolved = resolve_image_url_from_otp(otp, id_b64)
        if not resolved:
            return None, ("Invalid or expired otp, or id mismatch", 403)
        return resolved, None

    if not url:
        return None, ("url is required", 400)
    return url, None
