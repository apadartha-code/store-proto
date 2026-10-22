from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.config import Config
from app.services.backup import backup_database, safe_file_copy_backup
from app.services.categories import resolve_category_keys, set_image_categories
from app.services.errors import UploadValidationError
from app.services.image_download import resolve_download_url, send_image_download
from app.services.nickname import (
    find_images_by_nickname,
    set_user_nickname,
)
from app.services.query import get_image, list_images, random_images
from app.services.bulk_edit import bulk_update_metadata
from app.services.upload import (
    ingest_image,
    update_image_license,
    update_image_tags,
    validate_batch_limits,
)

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)


@api_bp.get("/image")
def download_image():
    url = request.args.get("url") or request.args.get("image_url")
    otp = request.args.get("otp")
    id_b64 = request.args.get("id")

    resolved_url, err = resolve_download_url(url=url, otp=otp, id_b64=id_b64)
    if err:
        message, code = err
        return jsonify({"error": message}), code

    response, err = send_image_download(resolved_url)
    if err:
        message, code = err
        return jsonify({"error": message}), code
    return response


@api_bp.post("/backup")
def api_backup():
    try:
        path = backup_database()
    except Exception:
        logger.error("Online backup failed; falling back to file copy", exc_info=True)
        path = safe_file_copy_backup()
    return jsonify({"ok": True, "path": str(path)})


@api_bp.post("/upload")
def api_upload():
    if "files" not in request.files:
        logger.error("Upload request missing files field")
        return jsonify({"error": "No files field"}), 400

    files = [f for f in request.files.getlist("files") if f.filename]
    if not files:
        logger.error("Upload request contained no files")
        return jsonify({"error": "No files uploaded"}), 400

    payloads: list[tuple] = []
    try:
        for f in files:
            payloads.append((f, f.read()))
        validate_batch_limits(
            len(payloads),
            sum(len(raw) for _, raw in payloads),
        )
    except UploadValidationError as e:
        return jsonify({"error": str(e)}), 400

    meta = {
        "sharing": request.form.get("sharing", "public"),
        "categories": request.form.getlist("categories"),
        "source": request.form.get("source"),
        "license": request.form.get("license"),
        "tags": request.form.get("tags", ""),
    }

    ids = []
    errors = []
    for f, raw in payloads:
        logger.info("Received upload file: %s", f.filename)
        try:
            image_id = ingest_image(f.filename, raw, meta)
            ids.append(image_id)
        except UploadValidationError as e:
            errors.append({"file": f.filename, "error": str(e)})
        except Exception:
            logger.error("Upload failed for %s", f.filename, exc_info=True)
            errors.append({"file": f.filename, "error": "Internal error"})

    if not ids and errors:
        return jsonify({"error": "Upload failed", "details": errors}), 400

    return jsonify({"image_ids": ids, "errors": errors})


@api_bp.get("/images")
def api_list_images():
    page = int(request.args.get("page", 1))
    category = request.args.get("category") or None
    sharing = request.args.get("sharing") or None
    q = (request.args.get("q") or "").strip() or None
    if request.args.get("random") and not q:
        items = random_images(
            limit=Config.PAGE_SIZE,
            category=category or "general",
            sharing=sharing or "public_and_shared",
        )
        return jsonify({"items": items, "page": 1, "pages": 1, "total": len(items)})

    tags = request.args.getlist("tag") or None
    result = list_images(
        page=page,
        per_page=Config.PAGE_SIZE,
        category=category,
        sharing=sharing,
        tags=tags,
        q=q,
        order="recent",
    )
    return jsonify(result)


@api_bp.get("/images/<image_id>")
def api_get_image(image_id: str):
    img = get_image(image_id)
    if not img:
        return jsonify({"error": "Not found"}), 404
    img["image_url"] = request.host_url.rstrip("/") + f"/i/{image_id}"
    return jsonify(img)


@api_bp.post("/images/bulk-edit")
def api_bulk_edit_images():
    """Features.md §4 — bulk category overwrite and tag merge."""
    data = request.get_json(silent=True) or {}
    image_ids = data.get("image_ids")
    if not isinstance(image_ids, list) or not image_ids:
        return jsonify({"error": "image_ids is required"}), 400

    category_keys = None
    if "categories" in data:
        keys = data["categories"]
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.split(",") if k.strip()]
        if not isinstance(keys, list):
            return jsonify({"error": "categories must be a list"}), 400
        category_keys = keys

    tags_to_add = None
    if "tags" in data:
        tags = data["tags"]
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        if not isinstance(tags, list):
            return jsonify({"error": "tags must be a list"}), 400
        tags_to_add = tags

    try:
        result = bulk_update_metadata(
            image_ids,
            category_keys=category_keys,
            tags_to_add=tags_to_add,
        )
    except UploadValidationError as exc:
        return jsonify({"error": str(exc)}), 400

    status = 200
    if result.get("failed"):
        result["partial"] = True
    return jsonify(result), status


@api_bp.patch("/images/<image_id>")
def api_patch_image(image_id: str):
    img = get_image(image_id)
    if not img:
        return jsonify({"error": "Not found"}), 404

    data = request.get_json(silent=True) or {}
    if "tags" in data:
        tags = data["tags"]
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        update_image_tags(image_id, tags)

    if "categories" in data:
        keys = data["categories"]
        if isinstance(keys, str):
            keys = [k.strip() for k in keys.split(",") if k.strip()]
        set_image_categories(image_id, resolve_category_keys(keys))

    if "license" in data and data["license"]:
        update_image_license(image_id, data["license"], img["sharing"])

    if "nickname" in data and data["nickname"]:
        set_user_nickname(image_id, data["nickname"])

    return api_get_image(image_id)


@api_bp.get("/nicknames/nearest")
def api_nearest_nickname():
    text = request.args.get("q", "")
    if not text:
        return jsonify({"error": "q is required"}), 400
    image_ids = find_images_by_nickname(text)
    if not image_ids:
        return jsonify({"error": "No images"}), 404
    items = []
    for image_id in image_ids:
        img = get_image(image_id)
        if img:
            items.append(
                {
                    "image": img,
                    "image_url": request.host_url.rstrip("/") + f"/i/{image_id}",
                    "thumbnail_url": f"/thumb/{image_id}",
                }
            )
    return jsonify({"items": items, "count": len(items)})
