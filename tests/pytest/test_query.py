"""Features.md §3 Gallery — fuzzy search weights."""

from __future__ import annotations

import io

from PIL import Image

from app.services.query import fuzzy_score


def test_fuzzy_score_weights():
    # Features.md §3 — tags > name > category/sharing
    img = {
        "tags": ["beach"],
        "original_name": "vacation.jpg",
        "category": "general",
        "sharing": "public",
    }
    tag_score = fuzzy_score("beach", img)
    name_score = fuzzy_score("vacation", img)
    cat_score = fuzzy_score("general", img)
    assert tag_score > name_score
    assert name_score > cat_score


def test_list_images_search(app):
    from app.services.query import list_images
    from app.services.upload import ingest_image

    raw = io.BytesIO()
    Image.new("RGB", (5, 5)).save(raw, "PNG")
    ingest_image(
        "findme.png",
        raw.getvalue(),
        {
            "sharing": "public",
            "category": "general",
            "source": "s",
            "tags": ["unicorn"],
        },
    )
    result = list_images(q="unicorn", category="general", sharing="public")
    assert result["total"] >= 1
