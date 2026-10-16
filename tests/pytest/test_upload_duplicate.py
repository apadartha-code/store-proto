"""Features.md §3 Upload — duplicate image bytes rejected after first ingest."""

from __future__ import annotations

import io

from PIL import Image


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (9, 7), color=(4, 5, 6)).save(buf, format="PNG")
    return buf.getvalue()


def _upload_one(client, filename: str, raw: bytes):
    return client.post(
        "/api/upload",
        data={
            "sharing": "private",
            "license": "Private",
            "categories": "General",
            "files": (io.BytesIO(raw), filename),
        },
        content_type="multipart/form-data",
    )


def test_duplicate_image_bytes_second_filename_rejected(client):
    """
    §3 — Same image content with a different original_name is a duplicate;
    only the first upload succeeds.
    """
    raw = _png_bytes()

    first = _upload_one(client, "photo-a.png", raw)
    assert first.status_code == 200
    body1 = first.get_json()
    assert len(body1["image_ids"]) == 1
    assert body1["errors"] == []

    second = _upload_one(client, "photo-b.png", raw)
    assert second.status_code == 400
    body2 = second.get_json()
    assert body2.get("image_ids") in (None, [])
    assert not body2.get("image_ids")
    errors = body2.get("details") or body2.get("errors") or []
    assert len(errors) == 1
    assert errors[0]["file"] == "photo-b.png"
    assert errors[0]["error"]

    from app.db import db_session

    with db_session() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"]
    assert count == 1


def test_duplicate_image_bytes_same_request_only_first_file_succeeds(client):
    """§3 — Within one batch, the second file with duplicate bytes is rejected."""
    raw = _png_bytes()
    res = client.post(
        "/api/upload",
        data={
            "sharing": "private",
            "license": "Private",
            "categories": "General",
            "files": [
                (io.BytesIO(raw), "first.png"),
                (io.BytesIO(raw), "second.png"),
            ],
        },
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    body = res.get_json()
    assert len(body["image_ids"]) == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["file"] == "second.png"

    from app.db import db_session

    with db_session() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"]
    assert count == 1
