from __future__ import annotations

from typing import Iterable

from app.db import db_session
from app.services.dictionary import get_dictionary
from app.services.errors import UploadValidationError


def resolve_category_keys(keys: Iterable[str]) -> list[int]:
    dd = get_dictionary()
    ids: list[int] = []
    for key in keys:
        k = (key or "").strip()
        if not k:
            continue
        cat = None
        for ck in dd.category_keys():
            if ck.lower() == k.lower():
                cat = dd.category_by_key(ck)
                break
        if not cat:
            raise UploadValidationError(f"Invalid category: {k}")
        ids.append(cat.id)
    if not ids:
        raise UploadValidationError("At least one category is required")
    return sorted(set(ids))


def set_image_categories(image_id: str, category_ids: list[int]) -> None:
    dd = get_dictionary()
    for cid in category_ids:
        if dd.category_by_id(cid) is None:
            raise UploadValidationError(f"Invalid category id: {cid}")
    with db_session() as conn:
        conn.execute("DELETE FROM image_categories WHERE image_id = ?", (image_id,))
        for cid in category_ids:
            conn.execute(
                "INSERT INTO image_categories (image_id, category_id) VALUES (?, ?)",
                (image_id, cid),
            )
