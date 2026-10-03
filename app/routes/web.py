from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
import io
import urllib.parse

from app.config import Config
from app.services.otp import create_otp
from app.services.fragments import reconstruct_image
from app.services.nickname import find_nearest_image_id, list_nicknames_for_image
from app.services.query import get_image, list_images
from app.services.thumbnail import thumbnail_path

web_bp = Blueprint("web", __name__)


def _recall_context_from_request() -> dict:
    callback = request.args.get("callback")
    redir = request.args.get("redir")
    idhash = request.args.get("idhash")

    if callback:
        return {
            "recall_mode": "callback",
            "callback": callback,
            "redir": None,
            "idhash": None,
        }
    if redir:
        return {
            "recall_mode": "redir",
            "callback": None,
            "redir": redir,
            "idhash": idhash,
        }
    return {
        "recall_mode": "callback",
        "callback": url_for("web.landing", _external=True),
        "redir": None,
        "idhash": None,
    }


def _recall_context_from_form() -> dict:
    mode = request.form.get("recall_mode", "callback")
    if mode == "redir":
        return {
            "recall_mode": "redir",
            "callback": None,
            "redir": request.form.get("redir"),
            "idhash": request.form.get("idhash"),
        }
    callback = request.form.get("callback") or url_for("web.landing", _external=True)
    return {
        "recall_mode": "callback",
        "callback": callback,
        "redir": None,
        "idhash": None,
    }


def _append_query(url: str, params: dict[str, str]) -> str:
    parts = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
    for key, value in params.items():
        query[key] = [value]
    new_query = urllib.parse.urlencode(query, doseq=True)
    return urllib.parse.urlunparse(parts._replace(query=new_query))


def _pager(page: int, pages: int) -> dict:
    page = max(1, min(page, pages))
    return {"page": page, "pages": pages}


@web_bp.get("/")
def landing():
    page = int(request.args.get("page", 1))
    category = request.args.get("category", "general")
    sharing = request.args.get("sharing", "public")
    random_mode = request.args.get("random") == "1"
    q = request.args.get("q", "").strip()
    search_mode = bool(q) and not random_mode

    order = "random" if random_mode else "recent"
    data = list_images(
        page=page,
        per_page=Config.PAGE_SIZE,
        category=category if category != "all" else None,
        sharing=sharing if sharing != "all" else None,
        q=q or None,
        order=order,
    )
    pager = _pager(data["page"], data["pages"])
    return render_template(
        "landing.html",
        images=data["items"],
        pager=pager,
        category=category,
        sharing=sharing,
        q=q,
        random_mode=random_mode,
        search_mode=search_mode,
    )


@web_bp.get("/image/<image_id>")
def image_detail(image_id: str):
    img = get_image(image_id)
    if not img:
        abort(404)
    nicknames = list_nicknames_for_image(image_id)
    return render_template(
        "detail.html",
        image=img,
        nicknames=nicknames,
        image_page_url=url_for("web.image_page", image_id=image_id, _external=True),
    )


@web_bp.get("/i/<image_id>")
def image_page(image_id: str):
    img = get_image(image_id)
    if not img:
        abort(404)
    return render_template("image_page.html", image=img)


@web_bp.get("/i/<image_id>/content")
def serve_image_bytes(image_id: str):
    try:
        raw, mime = reconstruct_image(image_id)
    except FileNotFoundError:
        abort(404)
    return send_file(io.BytesIO(raw), mimetype=mime)


@web_bp.get("/thumb/<image_id>")
def serve_thumbnail(image_id: str):
    path = thumbnail_path(image_id)
    if not path.exists():
        try:
            raw, mime = reconstruct_image(image_id)
            from app.services.thumbnail import generate_thumbnail

            generate_thumbnail(image_id, raw)
        except Exception:
            abort(404)
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="image/jpeg")


@web_bp.get("/recall")
def recall():
    ctx = _recall_context_from_request()
    if ctx["recall_mode"] == "redir" and not ctx["idhash"]:
        return render_template(
            "recall.html",
            **ctx,
            error="redir requires idhash query parameter",
        ), 400
    return render_template("recall.html", **ctx)


@web_bp.post("/recall/find")
def recall_find():
    ctx = _recall_context_from_form()
    nickname = request.form.get("nickname", "")
    image_id = find_nearest_image_id(nickname)
    if not image_id:
        return render_template(
            "recall.html",
            **ctx,
            error="No matching images in database",
            nickname=nickname,
        )
    img = get_image(image_id)
    image_url = url_for("web.image_page", image_id=image_id, _external=True)
    return render_template(
        "recall.html",
        **ctx,
        nickname=nickname,
        image=img,
        image_url=image_url,
        show_done=True,
    )


@web_bp.post("/recall/done")
def recall_done():
    ctx = _recall_context_from_form()
    image_url = request.form.get("image_url")
    if not image_url:
        abort(400)

    if ctx["recall_mode"] == "redir":
        redir = ctx.get("redir")
        idhash = ctx.get("idhash")
        if not redir or not idhash:
            abort(400)
        otp = create_otp(image_url, idhash)
        return redirect(_append_query(redir, {"otp": otp}))

    callback = ctx.get("callback")
    if not callback:
        abort(400)
    return render_template(
        "recall_done.html",
        callback=callback,
        image_url=image_url,
    )
