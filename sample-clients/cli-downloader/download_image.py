#!/usr/bin/env python3
"""Download an image from Image Store via POST /api/image."""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.I,
)


def api_base_from_image_url(image_url: str) -> str:
    parsed = urllib.parse.urlparse(image_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(
            "Image URL must be absolute (e.g. http://host:5000/i/<uuid>)"
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def image_id_from_url(image_url: str) -> str | None:
    path = urllib.parse.urlparse(image_url).path or image_url
    match = UUID_RE.search(path)
    return match.group(0).lower() if match else None


def filename_from_content_disposition(header: str | None) -> str | None:
    if not header:
        return None
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', header, re.I)
    return match.group(1).strip() if match else None


def default_output_path(image_url: str, content_type: str | None) -> Path:
    image_id = image_id_from_url(image_url) or "download"
    ext = mimetypes.guess_extension(content_type or "", strict=False) or ".bin"
    if ext == ".jpe":
        ext = ".jpg"
    return Path(f"{image_id}{ext}")


def download_image(image_url: str, api_base: str | None, output: Path | None) -> Path:
    base = api_base.rstrip("/") if api_base else api_base_from_image_url(image_url)
    endpoint = f"{base}/api/image"
    body = json.dumps({"url": image_url}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "*/*"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
            content_type = resp.headers.get("Content-Type")
            dest = output or default_output_path(
                image_url, content_type.split(";")[0].strip() if content_type else None
            )
            if output is None:
                cd_name = filename_from_content_disposition(
                    resp.headers.get("Content-Disposition")
                )
                if cd_name:
                    dest = Path(cd_name)
            dest.write_bytes(data)
            return dest
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(detail)
            message = err.get("error", detail)
        except json.JSONDecodeError:
            message = detail or exc.reason
        raise SystemExit(f"Download failed ({exc.code}): {message}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {endpoint}: {exc.reason}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download an image using POST /api/image (Image Store API).",
    )
    parser.add_argument(
        "image_url",
        help="Image page URL (e.g. http://localhost:5000/i/<uuid>)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output file path (default: derived from image id and MIME type)",
    )
    parser.add_argument(
        "--api-base",
        metavar="URL",
        help="Server base URL (default: scheme and host from image_url)",
    )
    args = parser.parse_args(argv)

    dest = download_image(args.image_url, args.api_base, args.output)
    print(dest.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
