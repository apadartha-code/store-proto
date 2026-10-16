"""Features.md §4 — bulk category/tag edit."""

from __future__ import annotations

import io

from PIL import Image


def _ingest(**meta):
    from app.services.upload import ingest_image

    raw = io.BytesIO()
    Image.new("RGB", (5, 5), color=meta.pop("color", (1, 1, 1))).save(raw, "PNG")
    data = raw.getvalue()
    defaults = {
        "sharing": "public",
        "categories": ["General"],
        "source": "t",
        "tags": ["alpha"],
    }
    defaults.update(meta)
    return ingest_image("bulk.png", data, defaults)


def test_merge_tags_case_insensitive(app):
    # Features.md §4 — bulk tag merge
    from app.services.query import get_image
    from app.services.tags import merge_tags_into_image

    image_id = _ingest(tags=["Alpha", "beta"])
    merge_tags_into_image(image_id, ["alpha", "Gamma"])
    img = get_image(image_id)
    tags = [t.lower() for t in img["tags"]]
    assert "alpha" in tags
    assert "beta" in tags
    assert "gamma" in tags
    assert tags.count("alpha") == 1


def test_bulk_update_overwrites_categories_and_merges_tags(app):
    from app.services.bulk_edit import bulk_update_metadata
    from app.services.query import get_image

    image_id = _ingest(categories=["General"], tags=["one"])
    result = bulk_update_metadata(
        [image_id],
        category_keys=["Adult"],
        tags_to_add=["two", "one"],
    )
    assert result["updated_count"] == 1
    img = get_image(image_id)
    assert any(c.lower() == "adult" for c in img["categories"])
    assert "one" in img["tags"] and "two" in img["tags"]


def test_api_bulk_edit(client, app):
    image_id = _ingest()
    res = client.post(
        "/api/images/bulk-edit",
        json={
            "image_ids": [image_id],
            "categories": ["General", "Adult"],
            "tags": ["bulk-tag"],
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["updated_count"] == 1
    detail = client.get(f"/api/images/{image_id}").get_json()
    assert "bulk-tag" in detail["tags"]
    assert len(detail["categories"]) == 2


def test_api_bulk_edit_requires_updates(client, app):
    image_id = _ingest()
    res = client.post(
        "/api/images/bulk-edit",
        json={"image_ids": [image_id]},
    )
    assert res.status_code == 400


def test_bulk_edit_page_renders(client):
    res = client.get("/bulk-edit")
    assert res.status_code == 200
    assert b"bulk-edit" in res.data
    assert b'data-testid="bulk-submit"' in res.data
    assert b'data-testid="category-cb-General"' in res.data


def test_landing_has_selection_controls(client, app):
    _ingest()
    res = client.get("/")
    assert res.status_code == 200
    assert b'data-testid="selection-select-all"' in res.data
    assert b'data-testid="search-clear"' in res.data
    assert b'gallery-select-cb' in res.data
