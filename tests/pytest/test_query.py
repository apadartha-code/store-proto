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


def test_list_images_search_ignores_random_order(app):
    # Features.md §4 — search uses score ranking, not random SQL order
    from app.services.query import list_images
    from app.services.upload import ingest_image

    raw = io.BytesIO()
    Image.new("RGB", (5, 5)).save(raw, "PNG")
    ingest_image(
        "low.png",
        raw.getvalue(),
        {
            "sharing": "public",
            "categories": ["General"],
            "source": "s",
            "tags": ["zzalpha"],
        },
    )
    raw2 = io.BytesIO()
    Image.new("RGB", (6, 6)).save(raw2, "PNG")
    better_id = ingest_image(
        "zzalpha.png",
        raw2.getvalue(),
        {
            "sharing": "public",
            "categories": ["General"],
            "source": "s",
            "tags": ["zzalpha"],
        },
    )
    ranked = list_images(
        q="zzalpha",
        category="general",
        sharing="public_and_shared",
        order="random",
    )
    assert ranked["items"][0]["id"] == better_id


def test_landing_hides_latest_random_during_search(client, app):
    # Features.md §4 — Latest/Random hidden while searching
    from app.services.query import list_images
    from app.services.upload import ingest_image

    raw = io.BytesIO()
    Image.new("RGB", (4, 4)).save(raw, "PNG")
    ingest_image(
        "modes.png",
        raw.getvalue(),
        {"sharing": "public", "categories": ["General"], "source": "s", "tags": ["modes"]},
    )
    assert list_images(q="modes")["total"] >= 1
    res = client.get("/?q=modes")
    assert res.status_code == 200
    assert b'data-testid="mode-latest"' not in res.data
    assert b'data-testid="mode-random"' not in res.data
    res2 = client.get("/")
    assert b'data-testid="mode-latest"' in res2.data


def test_landing_strips_random_when_searching(client):
    res = client.get("/?q=foo&random=1&category=general&sharing=public_and_shared")
    assert res.status_code == 302
    assert "random" not in res.location
    assert "q=foo" in res.location
