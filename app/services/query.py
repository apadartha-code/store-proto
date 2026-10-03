from __future__ import annotations

import difflib
import random
import re
from typing import Any, Optional

from app.db import db_session, row_to_image

WEIGHT_TAGS = 4.0
WEIGHT_NAME = 2.0
WEIGHT_CATEGORY = 1.0
WEIGHT_SHARING = 1.0

_TERM_SPLIT = re.compile(r"\s+")


def _build_filters(
    category: Optional[str],
    sharing: Optional[str],
) -> tuple[str, list[Any]]:
    clauses = ["1=1"]
    params: list[Any] = []

    if category:
        clauses.append("category = ?")
        params.append(category.lower())
    if sharing:
        clauses.append("sharing = ?")
        params.append(sharing.lower())

    return " AND ".join(clauses), params


def _term_matches_fuzzy(term: str, text: str) -> bool:
    if not text or not term:
        return False
    term_l = term.lower()
    text_l = text.lower()
    if term_l in text_l:
        return True
    for word in re.split(r"[\s_.,\-/]+", text_l):
        if not word:
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
    category = image.get("category") or ""
    sharing = image.get("sharing") or ""

    score = 0.0
    for term in terms:
        if _term_matches_fuzzy(term, tags_text):
            score += WEIGHT_TAGS
        if _term_matches_fuzzy(term, name):
            score += WEIGHT_NAME
        if _term_matches_fuzzy(term, category):
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
    sharing: Optional[str] = "public",
    tags: Optional[list[str]] = None,
    q: Optional[str] = None,
    order: str = "recent",
) -> dict[str, Any]:
    page = max(1, page)
    where, params = _build_filters(category, sharing)
    search_q = (q or "").strip()

    with db_session() as conn:
        if search_q and order != "random":
            rows = conn.execute(
                f"SELECT * FROM images WHERE {where}",
                params,
            ).fetchall()
            images = [row_to_image(r) for r in rows]
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
                where += ' AND tags LIKE ?'
                params.append(f'%"{tag}"%')

        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM images WHERE {where}", params
        ).fetchone()["c"]
        offset = (page - 1) * per_page
        rows = conn.execute(
            f"""
            SELECT * FROM images
            WHERE {where}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            [*params, per_page, offset],
        ).fetchall()

    return {
        "items": [row_to_image(r) for r in rows],
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


def get_image(image_id: str) -> Optional[dict[str, Any]]:
    with db_session() as conn:
        row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
    return row_to_image(row) if row else None


def random_images(
    limit: int = 60,
    category: Optional[str] = "general",
    sharing: Optional[str] = "public",
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
