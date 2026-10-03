"""Features.md §1 Storage — fragments; §2 Upload."""

from __future__ import annotations

import io

import pytest
from PIL import Image


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (12, 10), color=(1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


def test_fragment_roundtrip(app):
    # Features.md §1 — padded SHA-256 fragments reconstruct original
    from app.config import Config
    from app.services.fragments import split_into_fragments

    raw = _png_bytes()
    parts = split_into_fragments(raw, "public")
    assert parts
    frag_path = Config.FRAGMENTS_PUBLIC_DIR / parts[0][0]
    assert frag_path.is_file()


def test_ingest_and_reconstruct(app):
    from app.services.fragments import reconstruct_image
    from app.services.upload import ingest_image

    raw = _png_bytes()
    image_id = ingest_image(
        "shot.png",
        raw,
        {"sharing": "public", "category": "general", "source": "test", "tags": ["a"]},
    )
    got, mime = reconstruct_image(image_id)
    assert got == raw
    assert mime.startswith("image/")


def test_public_requires_source(app):
    from app.services.upload import UploadValidationError, ingest_image

    with pytest.raises(UploadValidationError):
        ingest_image("x.png", _png_bytes(), {"sharing": "public", "category": "general"})
