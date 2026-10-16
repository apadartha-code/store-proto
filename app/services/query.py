from __future__ import annotations

import difflib
import random
import re
from typing import Any, Optional

from app.config import Config
from app.db import db_session, row_to_image
from app.services.dictionary import get_dictionary

WEIGHT_TAGS = 4.0
WEIGHT_NAME = 2.0
WEIGHT_CATEGORY = 1.0
WEIGHT_SHARING = 1.0

_TERM_SPLIT = re.compile(r"\s+")


def _resolve_category_key(category: str) -> Optional[str]:
    dd = get_dictionary()
    for ck in dd.category_keys():
        if ck.lower() == category.lower():
            return ck
    return None


def _build_filters(
    category: Optional[str],
    sharing: Optional[str],
) -> tuple[str, list[Any]]:
    clauses = ["1=1"]
    params: list[Any] = []

    if category and category.lower() != "all":
        cat_key = _resolve_category_key(category)
        if cat_key:
            cat = get_dictionary().category_by_key(cat_key)
            if cat:
                clauses.append(
                    "images.id IN (SELECT image_id FROM image_categories WHERE category_id = ?)"
                )
                params.append(cat.id)
            else:
                clauses.append("1=0")
        else:
            clauses.append("1=0")

    if sharing:
        s = sharing.lower()
        if s == "public_and_shared":
            clauses.append("images.sharing IN ('public', 'shared')")
        elif s != "all":
            clauses.append("images.sharing = ?")
            params.append(s)

    return " AND ".join(clauses), params


def _term_matches_fuzzy(
    term: str,
    text: str,
    min_token_length: Optional[int] = None,
) -> bool:
    if not text or not term:
        return False
    if min_token_length is None:
        min_token_length = Config.FUZZY_MIN_TOKEN_LENGTH
    term_l = term.lower()
    text_l = text.lower()
    if term_l in text_l:
        return True
    for word in re.split(r"[\s_.,\-/]+", text_l):
        if not word or len(word) < min_token_length:
            continue
        if term_l in word or word in term_l:
            return True
        if difflib.SequenceMatcher(None, term_l, word).ratio() >= 0.62:
            return True
    return False


def fuzzy_score(query: str, image: dict[str, Any]) -> float:
    q = query.strip()
    if not q:
        return 0.0

    terms = [t for t in _TERM_SPLIT.split(q) if t]
    if not terms:
        terms = [q]

    tags_text = " ".join(image.get("tags") or [])
    name = image.get("original_name") or ""
    categories_text = " ".join(image.get("categories") or [])
    sharing = image.get("sharing") or ""

    score = 0.0
    for term in terms:
        if _term_matches_fuzzy(term, tags_text):
            score += WEIGHT_TAGS
        if _term_matches_fuzzy(term, name):
            score += WEIGHT_NAME
        if _term_matches_fuzzy(term, categories_text):
            score += WEIGHT_CATEGORY
        if _term_matches_fuzzy(term, sharing):
            score += WEIGHT_SHARING
    return score


def _paginate(items: list[Any], page: int, per_page: int) -> dict[str, Any]:
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "items": items[start:end],
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
    }


def list_images(
    page: int = 1,
    per_page: int = 60,
    category: Optional[str] = "general",
    sharing: Optional[str] = "public_and_shared",
    tags: Optional[list[str]] = None,
    q: Optional[str] = None,
    order: str = "recent",
) -> dict[str, Any]:
    page = max(1, page)
    where, params = _build_filters(category, sharing)
    search_q = (q or "").strip()

    with db_session() as conn:
        if search_q:
            rows = conn.execute(
                f"SELECT images.* FROM images WHERE {where}",
                params,
            ).fetchall()
            images = [row_to_image(r, conn) for r in rows]
            if tags:
                tag_set = {t.lower() for t in tags}
                images = [
                    img
                    for img in images
                    if tag_set.intersection({t.lower() for t in img.get("tags") or []})
                ]
            scored: list[tuple[float, str, dict[str, Any]]] = []
            for img in images:
                s = fuzzy_score(search_q, img)
                if s > 0:
                    scored.append((s, img["upload_time"], img))
            scored.sort(key=lambda row: (-row[0], row[1]), reverse=False)
            ranked = [img for _, _, img in scored]
            return _paginate(ranked, page, per_page)

        order_sql = "RANDOM()" if order == "random" else "upload_time DESC"
        if tags:
            for tag in tags:
                where += " AND images.tags LIKE ?"
                params.append(f'%"{tag}"%')

        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM images WHERE {where}", params
        ).fetchone()["c"]
        offset = (page - 1) * per_page
        rows = conn.execute(
            f"""
            SELECT images.* FROM images
            WHERE {where}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            [*params, per_page, offset],
        ).fetchall()
        items = [row_to_image(r, conn) for r in rows]

    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


def get_image(image_id: str) -> Optional[dict[str, Any]]:
    with db_session() as conn:
        row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
        return row_to_image(row, conn) if row else None


def random_images(
    limit: int = 60,
    category: Optional[str] = "general",
    sharing: Optional[str] = "public_and_shared",
) -> list[dict[str, Any]]:
    result = list_images(
        page=1,
        per_page=limit,
        category=category,
        sharing=sharing,
        order="random",
    )
    random.shuffle(result["items"])
    return result["items"]
