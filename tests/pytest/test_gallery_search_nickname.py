"""Features.md §4 Gallery search — nicknames must not affect fuzzy q search (§6)."""

from __future__ import annotations

import io
import json

from PIL import Image


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color=(1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


def _search_image_ids(q: str) -> list[str]:
    from app.services.query import list_images

    result = list_images(q=q, category="all", sharing="all", order="recent")
    return [item["id"] for item in result["items"]]


def test_fuzzy_score_ignores_nickname_field_on_image_dict():
    """§4 — weighted fields are tags, name, categories, sharing only."""
    from app.services.query import fuzzy_score

    img = {
        "tags": ["galaxy"],
        "original_name": "westerlund-2_42916480792_o",
        "categories": ["General"],
        "sharing": "public",
        "nickname": "the colour of god",
    }
    assert fuzzy_score("galaxy", img) > 0
    assert fuzzy_score("colour", img) == 0
    assert fuzzy_score("god", img) == 0


def test_gallery_q_does_not_match_nickname_words_after_tag_and_nickname_patch(
    app, client
):
    """
    §4 / §6 — Setting a user nickname must not make nickname terms discoverable
    via gallery search q; only indexed metadata (e.g. tags) should match.
    """
    from app.services.query import get_image
    from app.services.upload import ingest_image

    image_id = ingest_image(
        "frame-0001.png",
        _png(),
        {
            "sharing": "public",
            "categories": ["General"],
            "source": "test",
            "license": "Public Domain",
            "tags": [],
        },
    )

    for term in ("colour", "god", "galaxy"):
        assert image_id not in _search_image_ids(term)

    res = client.patch(
        f"/api/images/{image_id}",
        data=json.dumps(
            {
                "tags": ["galaxy"],
                "categories": ["General"],
                "license": "Public Domain",
                "nickname": "the colour of god",
            }
        ),
        content_type="application/json",
    )
    assert res.status_code == 200

    stored = get_image(image_id)
    assert stored is not None
    assert stored["tags"] == ["galaxy"]

    assert image_id in _search_image_ids("galaxy")
    assert image_id not in _search_image_ids("colour")
    assert image_id not in _search_image_ids("god")
