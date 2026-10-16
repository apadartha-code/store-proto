"""Features.md §3 Upload — duplicate image bytes and relaxed-sharing upgrades."""

from __future__ import annotations

import io

from PIL import Image


def _png_bytes(color: tuple[int, int, int] = (4, 5, 6)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (9, 7), color=color).save(buf, format="PNG")
    return buf.getvalue()


def _upload_one(
    client,
    filename: str,
    raw: bytes,
    *,
    sharing: str = "private",
    license: str = "Private",
    categories: str | list[str] = "General",
    tags: str = "",
    source: str = "",
):
    data: dict = {
        "sharing": sharing,
        "license": license,
        "files": (io.BytesIO(raw), filename),
    }
    if isinstance(categories, list):
        for cat in categories:
            data.setdefault("categories", [])
            if isinstance(data["categories"], list):
                data["categories"].append(cat)
    else:
        data["categories"] = categories
    if tags:
        data["tags"] = tags
    if sharing == "public":
        data["source"] = source or "test-source"
    return client.post(
        "/api/upload",
        data=data,
        content_type="multipart/form-data",
    )


def test_duplicate_image_bytes_second_filename_rejected(client):
    """
    §3 — Same image content with a different original_name is a duplicate;
    only the first upload succeeds.
    """
    raw = _png_bytes()

    first = _upload_one(client, "photo-a.png", raw)
    assert first.status_code == 200
    body1 = first.get_json()
    assert len(body1["image_ids"]) == 1
    assert body1["errors"] == []

    second = _upload_one(client, "photo-b.png", raw)
    assert second.status_code == 400
    body2 = second.get_json()
    assert body2.get("image_ids") in (None, [])
    assert not body2.get("image_ids")
    errors = body2.get("details") or body2.get("errors") or []
    assert len(errors) == 1
    assert errors[0]["file"] == "photo-b.png"
    assert errors[0]["error"]

    from app.db import db_session

    with db_session() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"]
    assert count == 1


def test_duplicate_image_bytes_same_request_only_first_file_succeeds(client):
    """§3 — Within one batch, the second file with duplicate bytes is rejected."""
    raw = _png_bytes()
    res = client.post(
        "/api/upload",
        data={
            "sharing": "private",
            "license": "Private",
            "categories": "General",
            "files": [
                (io.BytesIO(raw), "first.png"),
                (io.BytesIO(raw), "second.png"),
            ],
        },
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    body = res.get_json()
    assert len(body["image_ids"]) == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["file"] == "second.png"

    from app.db import db_session

    with db_session() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"]
    assert count == 1


def _fragment_ids_for_image(image_id: str) -> list[str]:
    from app.db import db_session

    with db_session() as conn:
        rows = conn.execute(
            "SELECT fragment_id FROM fragments WHERE image_id = ? ORDER BY fragment_index",
            (image_id,),
        ).fetchall()
    return [str(r["fragment_id"]) for r in rows]


def _assert_fragment_storage(
    frag_ids: list[str],
    *,
    in_public: bool,
    in_user: bool,
) -> None:
    from app.config import Config

    for fid in frag_ids:
        public_path = Config.FRAGMENTS_PUBLIC_DIR / fid
        user_path = Config.FRAGMENTS_USER_DIR / fid
        assert public_path.is_file() == in_public
        assert user_path.is_file() == in_user
        if not in_public:
            assert not public_path.exists()
        if not in_user:
            assert not user_path.exists()


def test_duplicate_relaxed_sharing_private_then_public_updates_image(client):
    """
    §3 — Duplicate bytes with more relaxed sharing (private → public) updates
    sharing and license on the existing row; does not insert a second image.
    """
    raw = _png_bytes(color=(10, 11, 12))
    first = _upload_one(client, "locked.png", raw, sharing="private", license="Private")
    assert first.status_code == 200
    image_id = first.get_json()["image_ids"][0]

    second = _upload_one(
        client,
        "published.png",
        raw,
        sharing="public",
        license="Public Domain",
        source="new-source",
    )
    assert second.status_code == 200
    body2 = second.get_json()
    assert body2["errors"] == []
    assert body2["image_ids"] == [image_id]

    from app.db import db_session
    from app.services.query import get_image

    stored = get_image(image_id)
    assert stored is not None
    assert stored["sharing"] == "public"
    assert stored["license"] == "Public Domain"

    with db_session() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"]
    assert count == 1


def test_duplicate_relaxed_sharing_moves_fragments_to_public_store(client):
    """§3 — Upgrading private → public moves fragment files from user/ to public/."""
    raw = _png_bytes(color=(20, 21, 22))
    first = _upload_one(client, "a.png", raw, sharing="private", license="Private")
    image_id = first.get_json()["image_ids"][0]
    frag_ids = _fragment_ids_for_image(image_id)
    assert frag_ids
    _assert_fragment_storage(frag_ids, in_public=False, in_user=True)

    second = _upload_one(
        client,
        "b.png",
        raw,
        sharing="public",
        license="Public Domain",
    )
    assert second.status_code == 200

    _assert_fragment_storage(frag_ids, in_public=True, in_user=False)


def test_duplicate_relaxed_sharing_private_to_shared_fragments_stay_in_user_store(
    client,
):
    """
    §3 — private and shared both use fragments/user/; relaxing private → shared
    does not move files to public/.
    """
    raw = _png_bytes(color=(81, 82, 83))
    first = _upload_one(client, "p.png", raw, sharing="private", license="Private")
    image_id = first.get_json()["image_ids"][0]
    frag_ids = _fragment_ids_for_image(image_id)
    _assert_fragment_storage(frag_ids, in_public=False, in_user=True)

    second = _upload_one(
        client,
        "s.png",
        raw,
        sharing="shared",
        license="Unknown",
    )
    assert second.status_code == 200
    assert second.get_json()["image_ids"] == [image_id]
    _assert_fragment_storage(frag_ids, in_public=False, in_user=True)


def test_duplicate_relaxed_sharing_shared_to_public_moves_fragments_to_public_store(
    client,
):
    """§3 — Relaxing shared → public moves fragment files from user/ to public/."""
    raw = _png_bytes(color=(84, 85, 86))
    first = _upload_one(client, "sh.png", raw, sharing="shared", license="Unknown")
    image_id = first.get_json()["image_ids"][0]
    frag_ids = _fragment_ids_for_image(image_id)
    _assert_fragment_storage(frag_ids, in_public=False, in_user=True)

    second = _upload_one(
        client,
        "pub.png",
        raw,
        sharing="public",
        license="Public Domain",
    )
    assert second.status_code == 200
    assert second.get_json()["image_ids"] == [image_id]
    _assert_fragment_storage(frag_ids, in_public=True, in_user=False)


def test_duplicate_tightened_sharing_public_to_private_leaves_fragments_in_public(
    client,
):
    """
    §3 — Rejected duplicate (public → private) does not move fragments out of
    public/ or change the stored image sharing.
    """
    raw = _png_bytes(color=(87, 88, 89))
    first = _upload_one(
        client,
        "was-public.png",
        raw,
        sharing="public",
        license="Public Domain",
    )
    assert first.status_code == 200
    image_id = first.get_json()["image_ids"][0]
    frag_ids = _fragment_ids_for_image(image_id)
    _assert_fragment_storage(frag_ids, in_public=True, in_user=False)

    second = _upload_one(
        client,
        "tighten.png",
        raw,
        sharing="private",
        license="Private",
    )
    assert second.status_code == 400

    from app.services.query import get_image

    stored = get_image(image_id)
    assert stored["sharing"] == "public"
    assert stored["license"] == "Public Domain"
    _assert_fragment_storage(frag_ids, in_public=True, in_user=False)


def test_duplicate_relaxed_sharing_private_then_shared_updates_license(client):
    """§3 — private → shared is a relaxation; license may change to match sharing."""
    raw = _png_bytes(color=(30, 31, 32))
    first = _upload_one(client, "one.png", raw, sharing="private", license="Private")
    image_id = first.get_json()["image_ids"][0]

    second = _upload_one(
        client,
        "two.png",
        raw,
        sharing="shared",
        license="Unknown",
    )
    assert second.status_code == 200
    assert second.get_json()["image_ids"] == [image_id]

    from app.services.query import get_image

    stored = get_image(image_id)
    assert stored["sharing"] == "shared"
    assert stored["license"] == "Unknown"


def test_duplicate_relaxed_sharing_keeps_other_metadata_unchanged(client):
    """
    §3 — On relaxation upgrade, tags, categories, original_name, and source
    (non-target fields) are not overwritten by the second upload.
    """
    raw = _png_bytes(color=(40, 41, 42))
    first = _upload_one(
        client,
        "keep-name.png",
        raw,
        sharing="private",
        license="Private",
        categories=["General"],
        tags="galaxy",
    )
    image_id = first.get_json()["image_ids"][0]

    second = _upload_one(
        client,
        "ignore-name.png",
        raw,
        sharing="public",
        license="Public Domain",
        categories=["Adult"],
        tags="other",
        source="should-not-stick",
    )
    assert second.status_code == 200

    from app.services.query import get_image

    stored = get_image(image_id)
    assert stored["original_name"] == "keep-name.png"
    assert stored["tags"] == ["galaxy"]
    assert stored["categories"] == ["General"]
    assert stored["source"] is None


def test_duplicate_stricter_sharing_still_rejected(client):
    """§3 — public then private (stricter) remains a duplicate error."""
    raw = _png_bytes(color=(50, 51, 52))
    first = _upload_one(
        client,
        "pub.png",
        raw,
        sharing="public",
        license="Public Domain",
    )
    assert first.status_code == 200

    second = _upload_one(
        client,
        "priv.png",
        raw,
        sharing="private",
        license="Private",
    )
    assert second.status_code == 400
    errors = second.get_json().get("details") or second.get_json().get("errors") or []
    assert len(errors) == 1
    assert errors[0]["file"] == "priv.png"

    from app.db import db_session

    with db_session() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"]
    assert count == 1


def test_duplicate_same_sharing_still_rejected(client):
    """§3 — Same relaxation level (shared → shared) is not an upgrade; reject."""
    raw = _png_bytes(color=(60, 61, 62))
    first = _upload_one(
        client,
        "s1.png",
        raw,
        sharing="shared",
        license="Unknown",
    )
    assert first.status_code == 200

    second = _upload_one(
        client,
        "s2.png",
        raw,
        sharing="shared",
        license="Platform Contributed",
    )
    assert second.status_code == 400

    from app.db import db_session

    with db_session() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"]
    assert count == 1


def test_duplicate_relaxed_sharing_second_request_upgrades_after_strict_batch(client):
    """
    §3 — After a private upload, a later public upload of the same bytes upgrades
    the existing image (separate requests; batch metadata is per request).
    """
    raw = _png_bytes(color=(70, 71, 72))
    res = client.post(
        "/api/upload",
        data={
            "sharing": "private",
            "license": "Private",
            "categories": "General",
            "files": [(io.BytesIO(raw), "first.png")],
        },
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    image_id = res.get_json()["image_ids"][0]

    res2 = _upload_one(
        client,
        "upgrade.png",
        raw,
        sharing="public",
        license="Public Domain",
    )
    assert res2.status_code == 200
    assert res2.get_json()["image_ids"] == [image_id]

    from app.services.query import get_image

    stored = get_image(image_id)
    assert stored["sharing"] == "public"
    assert stored["license"] == "Public Domain"


def test_duplicate_relax_private_to_public_fallback_when_fragment_missing(
    client,
):
    """
    §3 — If relocate fails (missing fragment file), ingest re-splits bytes for the
    new sharing so the upgrade still succeeds.
    """
    from app.config import Config
    from app.services.fragments import reconstruct_image

    raw = _png_bytes(color=(91, 92, 93))
    first = _upload_one(client, "a.png", raw, sharing="private", license="Private")
    image_id = first.get_json()["image_ids"][0]
    frag_ids = _fragment_ids_for_image(image_id)
    assert frag_ids
    (Config.FRAGMENTS_USER_DIR / frag_ids[0]).unlink()

    second = _upload_one(
        client,
        "b.png",
        raw,
        sharing="public",
        license="Public Domain",
    )
    assert second.status_code == 200
    assert second.get_json()["image_ids"] == [image_id]
    _assert_fragment_storage(frag_ids, in_public=True, in_user=False)

    got, _ = reconstruct_image(image_id)
    assert got == raw


def test_duplicate_relax_shared_to_public_fallback_when_fragment_missing(
    client,
):
    """§3 — Same relocate fallback path for shared → public relaxation."""
    from app.config import Config
    from app.services.fragments import reconstruct_image
    from app.services.query import get_image

    raw = _png_bytes(color=(94, 95, 96))
    first = _upload_one(client, "s1.png", raw, sharing="shared", license="Unknown")
    image_id = first.get_json()["image_ids"][0]
    frag_ids = _fragment_ids_for_image(image_id)
    (Config.FRAGMENTS_USER_DIR / frag_ids[0]).unlink()

    second = _upload_one(
        client,
        "s2.png",
        raw,
        sharing="public",
        license="Public Domain",
    )
    assert second.status_code == 200
    assert second.get_json()["image_ids"] == [image_id]

    stored = get_image(image_id)
    assert stored["sharing"] == "public"
    _assert_fragment_storage(frag_ids, in_public=True, in_user=False)
    got, _ = reconstruct_image(image_id)
    assert got == raw
