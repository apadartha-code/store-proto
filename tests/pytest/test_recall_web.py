"""Features.md §5 — recall callback vs redir."""

from __future__ import annotations

import base64
import hashlib


def test_recall_callback_wins_over_redir(client):
    # Features.md §5 — callback ignores redir
    res = client.get(
        "/recall?callback=http://cb.example/done"
        "&redir=http://redir.example/r&idhash=abc"
    )
    assert res.status_code == 200
    assert b'name="recall_mode" value="callback"' in res.data
    assert b"http://cb.example/done" in res.data


def test_recall_redir_mode(client):
    idhash = base64.b64encode(hashlib.md5(b"id").digest()).decode("ascii")
    res = client.get(f"/recall?redir=http://app.example/otp&idhash={idhash}")
    assert res.status_code == 200
    assert b'name="recall_mode" value="redir"' in res.data


def test_recall_setup_link_new_tab(client):
    res = client.get("/recall")
    assert res.status_code == 200
    assert b"Setup nicknames" in res.data
    assert b'target="_blank"' in res.data
