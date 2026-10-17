"""Features.md §7 — recall redir mode."""

from __future__ import annotations

import base64
import hashlib


def test_recall_rejects_callback_query(client):
    res = client.get("/recall?callback=http://cb.example/done")
    assert res.status_code == 400
    assert b"callback query parameter is not supported" in res.data
    assert b'name="recall_mode" value="callback"' not in res.data


def test_recall_redir_mode(client):
    idhash = base64.b64encode(hashlib.md5(b"id").digest()).decode("ascii")
    res = client.get(f"/recall?redir=http://app.example/otp&idhash={idhash}")
    assert res.status_code == 200
    assert b'name="recall_mode" value="redir"' in res.data


def test_recall_browse_mode_default(client):
    res = client.get("/recall")
    assert res.status_code == 200
    assert b'name="recall_mode" value="browse"' in res.data


def test_recall_done_browse_redirects_home(client, app):
    from app.services.upload import ingest_image
    import io
    from PIL import Image

    raw = io.BytesIO()
    Image.new("RGB", (3, 3)).save(raw, "PNG")
    image_id = ingest_image(
        "rec.png",
        raw.getvalue(),
        {"sharing": "public", "categories": ["General"], "source": "t", "tags": ["recallme"]},
    )
    find = client.post(
        "/recall/find",
        data={"recall_mode": "browse", "nickname": "recallme"},
    )
    assert find.status_code == 200
    image_url = f"http://localhost/i/{image_id}"
    res = client.post(
        "/recall/done",
        data={
            "recall_mode": "browse",
            "image_urls": image_url,
        },
    )
    assert res.status_code == 302
    assert res.location.endswith("/")


def test_recall_setup_link_new_tab(client):
    res = client.get("/recall")
    assert res.status_code == 200
    assert b"Setup nicknames" in res.data
    assert b'target="_blank"' in res.data
    assert b'name="nickname"' in res.data and b'autocomplete="off"' in res.data
