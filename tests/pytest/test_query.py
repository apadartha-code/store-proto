"""Features.md §4 Gallery — fuzzy search and sharing filter."""

from __future__ import annotations

import io

from PIL import Image

from app.config import Config
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


def test_fuzzy_min_token_length_ignores_short_filename_segments():
    # Features.md §4 — FUZZY_MIN_TOKEN_LENGTH (default 3)
    img = {
        "tags": ["galaxy"],
        "original_name": "westerlund-2_42916480792_o",
        "categories": ["General"],
        "sharing": "public",
    }
    assert fuzzy_score("colour", img) == 0
    assert fuzzy_score("god", img) == 0
    assert fuzzy_score("galaxy", img) > 0


def test_fuzzy_min_token_length_configurable(monkeypatch):
    # Features.md §4 — lower min length restores short-token word match
    monkeypatch.setattr(Config, "FUZZY_MIN_TOKEN_LENGTH", 1)
    img = {
        "tags": [],
        "original_name": "westerlund-2_42916480792_o",
        "categories": [],
        "sharing": "public",
    }
    assert fuzzy_score("colour", img) > 0
    assert fuzzy_score("god", img) > 0


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
