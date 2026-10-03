"""Features.md §6 Image download API."""

from __future__ import annotations

import base64
import io
import secrets
import urllib.parse

from PIL import Image


def _ingest():
    from app.services.upload import ingest_image

    raw = io.BytesIO()
    Image.new("RGB", (7, 7)).save(raw, "PNG")
    data = raw.getvalue()
    image_id = ingest_image(
        "dl.png",
        data,
        {"sharing": "public", "category": "general", "source": "t"},
    )
    return image_id, data


def test_get_download_by_url(client, app):
    image_id, data = _ingest()
    url = f"http://localhost/i/{image_id}"
    res = client.get("/api/image?url=" + urllib.parse.quote(url))
    assert res.status_code == 200
    assert res.data == data


def test_post_download_by_url(client, app):
    image_id, data = _ingest()
    url = f"http://localhost/i/{image_id}"
    res = client.post("/api/image", json={"url": url})
    assert res.status_code == 200
    assert res.data == data


def test_get_download_by_otp(client, app):
    from app.services.otp import create_otp, idhash_for_id_bytes

    image_id, data = _ingest()
    image_url = f"http://localhost/i/{image_id}"
    id_bytes = secrets.token_bytes(16)
    id_b64 = base64.b64encode(id_bytes).decode("ascii")
    otp = create_otp(image_url, idhash_for_id_bytes(id_bytes))
    res = client.get(f"/api/image?otp={otp}&id={urllib.parse.quote(id_b64)}")
    assert res.status_code == 200
    assert res.data == data
    res2 = client.get(f"/api/image?otp={otp}&id={urllib.parse.quote(id_b64)}")
    assert res2.status_code == 403
