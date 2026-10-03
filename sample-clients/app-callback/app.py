#!/usr/bin/env python3
"""Minimal recall callback demo (port 4999 by default)."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, send_file, url_for

LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "4999"))
TMP_PREFIX = "image-store-recall-"

app = Flask(__name__)


def normalize_store_base(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("Image store host is required")
    if not value.startswith(("http://", "https://")):
        value = "http://" + value
    return value.rstrip("/")


def download_via_api(image_url: str) -> Path:
    parsed = urllib.parse.urlparse(image_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Invalid image_url")
    api_endpoint = f"{parsed.scheme}://{parsed.netloc}/api/image"
    body = json.dumps({"url": image_url}).encode("utf-8")
    req = urllib.request.Request(
        api_endpoint,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
        content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
        ext = mimetypes.guess_extension(content_type, strict=False) or ".bin"
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

    callback = url_for("callback", _external=True)
    query = urllib.parse.urlencode({"callback": callback})
    return redirect(f"{store_base}/recall?{query}")


@app.post("/callback")
def callback():
    image_url = request.form.get("image_url")
    if not image_url:
        return render_template("result.html", error="Missing image_url in callback"), 400
    try:
        path = download_via_api(image_url)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
        return render_template(
            "result.html",
            error=f"Download failed: {exc}",
            image_url=image_url,
        ), 502

    return redirect(url_for("show_result", token=path.name))


@app.get("/result/<token>")
def show_result(token: str):
    path = safe_tmp_path(token)
    return render_template(
        "result.html",
        token=token,
        saved_path=str(path),
    )


@app.get("/files/<token>")
def serve_file(token: str):
    path = safe_tmp_path(token)
    return send_file(path)


def main() -> None:
    app.run(host="0.0.0.0", port=LISTEN_PORT, debug=False)


if __name__ == "__main__":
    main()
