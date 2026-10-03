from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.config import Config
from app.services.backup import backup_database, safe_file_copy_backup
from app.services.image_download import resolve_download_url, send_image_download
from app.services.nickname import find_nearest_image_id, list_nicknames_for_image, try_add_nickname
from app.services.query import get_image, list_images, random_images
from app.services.upload import UploadValidationError, ingest_image, update_image_tags

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)

@api_bp.route("/image", methods=["GET", "POST"])
def download_image():
    url = None
    otp = None
    id_b64 = None

    if request.method == "GET":
        url = request.args.get("url") or request.args.get("image_url")
        otp = request.args.get("otp")
        id_b64 = request.args.get("id")
    else:
        data = request.get_json(silent=True) or {}
        url = data.get("url") or data.get("image_url")
        otp = data.get("otp")
        id_b64 = data.get("id")

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

    files = request.files.getlist("files")
    if not files:
        logger.error("Upload request contained no files")
        return jsonify({"error": "No files uploaded"}), 400

    meta = {
        "sharing": request.form.get("sharing", "public"),
        "category": request.form.get("category", "general"),
        "source": request.form.get("source"),
        "license": request.form.get("license"),
        "tags": request.form.get("tags", ""),
    }

    ids = []
    errors = []
    for f in files:
        if not f.filename:
            continue
        logger.info("Received upload file: %s", f.filename)
        try:
            raw = f.read()
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
    if request.args.get("random"):
        items = random_images(
            limit=Config.PAGE_SIZE,
            category=category or "general",
            sharing=sharing or "public",
        )
        return jsonify({"items": items, "page": 1, "pages": 1, "total": len(items)})

    tags = request.args.getlist("tag") or None
    q = request.args.get("q")
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
    nicknames = list_nicknames_for_image(image_id)
    img["nicknames"] = nicknames
    img["image_url"] = request.host_url.rstrip("/") + f"/i/{image_id}"
    return jsonify(img)


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

    if "nickname" in data and data["nickname"]:
        added = try_add_nickname(image_id, data["nickname"])
        if not added:
            logger.error(
                "Nickname add failed for image_id=%s: conflict or invalid",
                image_id,
            )
            return jsonify({"error": "Nickname conflict or invalid"}), 409

    return api_get_image(image_id)


@api_bp.get("/nicknames/nearest")
def api_nearest_nickname():
    text = request.args.get("q", "")
    if not text:
        return jsonify({"error": "q is required"}), 400
    image_id = find_nearest_image_id(text)
    if not image_id:
        return jsonify({"error": "No images"}), 404
    img = get_image(image_id)
    return jsonify(
        {
            "image": img,
            "image_url": request.host_url.rstrip("/") + f"/i/{image_id}",
            "thumbnail_url": f"/thumb/{image_id}",
        }
    )
