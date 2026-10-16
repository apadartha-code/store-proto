"""Features.md §2 Storage — fragments; §3 Upload."""

from __future__ import annotations

import io

import pytest
from PIL import Image


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (12, 10), color=(1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


def test_relocate_fragments_for_sharing_change_moves_to_public(app):
    # Features.md §2 — duplicate relax shared/private → public
    from app.config import Config
    from app.services.fragments import relocate_fragments_for_sharing_change, split_into_fragments

    raw = _png_bytes()
    parts = split_into_fragments(raw, "private")
    frag_ids = [fid for fid, _ in parts]
    for fid in frag_ids:
        assert (Config.FRAGMENTS_USER_DIR / fid).is_file()

    relocate_fragments_for_sharing_change(frag_ids, "private", "public")
    for fid in frag_ids:
        assert (Config.FRAGMENTS_PUBLIC_DIR / fid).is_file()
        assert not (Config.FRAGMENTS_USER_DIR / fid).exists()

    relocate_fragments_for_sharing_change(frag_ids, "private", "shared")
    for fid in frag_ids:
        assert (Config.FRAGMENTS_PUBLIC_DIR / fid).is_file()


def test_fragment_roundtrip(app):
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
        {
            "sharing": "public",
            "categories": ["General"],
            "source": "test",
            "tags": ["a"],
        },
    )
    got, mime = reconstruct_image(image_id)
    assert got == raw
    assert mime.startswith("image/")


def test_public_requires_source(app):
    from app.services.errors import UploadValidationError
    from app.services.upload import ingest_image

    with pytest.raises(UploadValidationError):
        ingest_image(
            "x.png",
            _png_bytes(),
            {"sharing": "public", "categories": ["General"]},
        )


def test_batch_upload_limits(app):
    from app.services.errors import UploadValidationError
    from app.services.upload import validate_batch_limits

    with pytest.raises(UploadValidationError):
        validate_batch_limits(51, 1000)
