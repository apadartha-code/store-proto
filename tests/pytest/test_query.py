"""Features.md §4 Gallery — fuzzy search and sharing filter."""

from __future__ import annotations

import io

from PIL import Image

from app.services.query import fuzzy_score


def test_fuzzy_score_weights():
    # Features.md §4 — tags > name > categories/sharing
    img = {
        "tags": ["beach"],
        "original_name": "vacation.jpg",
        "categories": ["General"],
        "sharing": "public",
    }
    tag_score = fuzzy_score("beach", img)
    name_score = fuzzy_score("vacation", img)
    cat_score = fuzzy_score("general", img)
    assert tag_score > name_score
    assert name_score >= cat_score


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
            "categories": ["General"],
            "source": "s",
            "tags": ["unicorn"],
        },
    )
    result = list_images(q="unicorn", category="general", sharing="public_and_shared")
    assert result["total"] >= 1
