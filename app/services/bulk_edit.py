from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from app.services.categories import resolve_category_keys, set_image_categories
from app.services.errors import UploadValidationError
from app.services.query import get_image
from app.services.tags import merge_tags_into_image

logger = logging.getLogger(__name__)


def bulk_update_metadata(
    image_ids: Sequence[str],
    *,
    category_keys: Optional[Sequence[str]] = None,
    tags_to_add: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """
    Update many images: categories replace when provided; tags merge when provided.
    """
    if not image_ids:
        raise UploadValidationError("No images selected")
    if category_keys is None and not tags_to_add:
        raise UploadValidationError("No updates specified")

    category_ids: Optional[list[int]] = None
    if category_keys is not None:
        category_ids = resolve_category_keys(category_keys)

    tag_list: list[str] = []
    if tags_to_add is not None:
        tag_list = [t.strip() for t in tags_to_add if (t or "").strip()]

    updated: list[str] = []
    failed: list[dict[str, str]] = []

    for image_id in image_ids:
        if get_image(image_id) is None:
            failed.append({"id": image_id, "error": "Not found"})
            continue
        try:
            changed = False
            if category_ids is not None:
                set_image_categories(image_id, category_ids)
                changed = True
            if tags_to_add is not None and tag_list:
                merge_tags_into_image(image_id, tag_list)
                changed = True
            if not changed:
                failed.append({"id": image_id, "error": "No updates applied"})
                continue
            updated.append(image_id)
        except UploadValidationError as exc:
            logger.error("Bulk edit failed for %s: %s", image_id, exc)
            failed.append({"id": image_id, "error": str(exc)})
        except Exception:
            logger.exception("Bulk edit failed for %s", image_id)
            failed.append({"id": image_id, "error": "Internal error"})

    if not updated and failed:
        raise UploadValidationError("Bulk edit failed for all selected images")

    return {"updated": updated, "failed": failed, "updated_count": len(updated)}
