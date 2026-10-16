"""Features.md §5 — image detail page."""

from __future__ import annotations

import io

from PIL import Image


def _ingest():
    from app.services.upload import ingest_image

    raw = io.BytesIO()
    Image.new("RGB", (6, 6)).save(raw, "PNG")
    return ingest_image(
        "detail.png",
        raw.getvalue(),
        {"sharing": "public", "categories": ["General"], "source": "t"},
    )


def test_detail_page_has_save_acknowledgement_overlays(client, app):
    image_id = _ingest()
    res = client.get(f"/image/{image_id}")
    assert res.status_code == 200
    assert b'data-testid="detail-save"' in res.data
    assert b'data-testid="detail-overlay-success"' in res.data
    assert b'data-testid="detail-overlay-failure"' in res.data
    assert b'data-testid="detail-overlay-failure-dismiss"' in res.data
    assert b'data-testid="category-cb-General"' in res.data
