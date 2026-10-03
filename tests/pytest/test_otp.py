"""Features.md §5 Nickname recall — OTP / idhash."""

from __future__ import annotations

import base64
import secrets

from app.services.otp import (
    create_otp,
    id_matches_idhash,
    idhash_for_id_bytes,
    resolve_image_url_from_otp,
)


def test_idhash_and_match():
    # Features.md §5 — idhash = base64(md5(id bytes))
    id_bytes = secrets.token_bytes(20)
    id_b64 = base64.b64encode(id_bytes).decode("ascii")
    idhash = idhash_for_id_bytes(id_bytes)
    assert id_matches_idhash(id_b64, idhash)
    assert not id_matches_idhash(id_b64, "invalid")


def test_otp_single_use_and_url():
    # Features.md §5–§6 — OTP consumed; image URL resolved
    id_bytes = b"client-secret-id"
    idhash = idhash_for_id_bytes(id_bytes)
    id_b64 = base64.b64encode(id_bytes).decode("ascii")
    image_url = "http://example/i/00000000-0000-4000-8000-000000000001"
    otp = create_otp(image_url, idhash)

    assert resolve_image_url_from_otp(otp, id_b64) == image_url
    assert resolve_image_url_from_otp(otp, id_b64) is None


def test_otp_wrong_id():
    id_bytes = b"a"
    idhash = idhash_for_id_bytes(id_bytes)
    otp = create_otp("http://x/i/u", idhash)
    wrong = base64.b64encode(b"b").decode("ascii")
    assert resolve_image_url_from_otp(otp, wrong) is None
