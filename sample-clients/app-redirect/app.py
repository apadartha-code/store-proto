#!/usr/bin/env python3
"""Recall integration demo using redir + OTP (port 4998 by default)."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, send_file, session, url_for

LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "4998"))
TMP_PREFIX = "image-store-redirect-"
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-sample-app-redirect")


def normalize_store_base(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("Image store host is required")
    if not value.startswith(("http://", "https://")):
        value = "http://" + value
    return value.rstrip("/")


def download_via_otp(store_base: str, otp: str, id_b64: str) -> bytes:
    query = urllib.parse.urlencode({"otp": otp, "id": id_b64})
    endpoint = f"{store_base}/api/image?{query}"
    req = urllib.request.Request(endpoint, method="GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def save_image_bytes(data: bytes, content_type: str | None) -> Path:
    ext = mimetypes.guess_extension(content_type or "", strict=False) or ".bin"
    if ext == ".jpe":
        ext = ".jpg"
    name = f"{TMP_PREFIX}{secrets.token_hex(16)}{ext}"
    path = Path("/tmp") / name
    path.write_bytes(data)
    return path


def safe_tmp_path(token: str) -> Path:
    if not re.fullmatch(rf"{TMP_PREFIX}[0-9a-f]{{32}}\.[a-z0-9]+", token, re.I):
        abort(404)
    path = Path("/tmp") / token
    if not path.is_file():
        abort(404)
    return path


@app.get("/")
def index():
    return render_template("index.html", port=LISTEN_PORT)


@app.post("/go-recall")
def go_recall():
    store_raw = request.form.get("store_host", "")
    try:
        store_base = normalize_store_base(store_raw)
    except ValueError as exc:
        return (
            render_template(
                "index.html", error=str(exc), store_host=store_raw, port=LISTEN_PORT
            ),
            400,
        )

    id_bytes = secrets.token_bytes(24)
    id_b64 = base64.b64encode(id_bytes).decode("ascii")
    idhash = base64.b64encode(hashlib.md5(id_bytes).digest()).decode("ascii")
    session["download_id_b64"] = id_b64
    session["store_base"] = store_base

    redir = url_for("otp_receiver", _external=True)
    query = urllib.parse.urlencode({"redir": redir, "idhash": idhash})
    return redirect(f"{store_base}/recall?{query}")


@app.get("/otp-receiver")
def otp_receiver():
    otp = request.args.get("otp")
    id_b64 = session.get("download_id_b64")
    store_base = session.get("store_base")
    if not otp or not id_b64 or not store_base:
        return render_template(
            "result.html",
            error="Missing otp session state. Start again from the home page.",
        ), 400

    try:
        data = download_via_otp(store_base, otp, id_b64)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        return render_template("result.html", error=f"Download failed: {exc}"), 502

    path = save_image_bytes(data, "image/jpeg")
    session.pop("download_id_b64", None)
    return redirect(url_for("show_result", token=path.name))


@app.get("/result/<token>")
def show_result(token: str):
    path = safe_tmp_path(token)
    return render_template("result.html", token=token, saved_path=str(path))


@app.get("/files/<token>")
def serve_file(token: str):
    return send_file(safe_tmp_path(token))


def main() -> None:
    app.run(host="0.0.0.0", port=LISTEN_PORT, debug=False)


if __name__ == "__main__":
    main()
