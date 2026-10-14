#!/usr/bin/env python3
"""Batch upload images to Image Store POST /api/upload."""

from __future__ import annotations

import argparse
import glob
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, TextIO

_LIMIT_KEYS = (
    "MAX_UPLOAD_KB",
    "MAX_UPLOAD_TOTAL_BYTES",
    "MAX_UPLOAD_FILE_COUNT",
)

_IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


@dataclass(frozen=True)
class UploadLimits:
    max_file_bytes: int
    max_batch_bytes: int
    max_batch_files: int


@dataclass
class PreparedFile:
    path: Path
    size: int
    mime: str


@dataclass
class BatchPlan:
    batches: list[list[PreparedFile]]
    rejected_size: list[tuple[Path, str]]
    skipped_mime: list[Path]


def _parse_positive_int(name: str, raw: str) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a positive integer, got: {raw!r}")
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer, got: {value}")
    return value


def parse_dotenv_lines(lines: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        out[key] = value
    return out


def load_dotenv_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    return parse_dotenv_lines(path.read_text(encoding="utf-8").splitlines())


def resolve_upload_limits(
    *,
    dotenv_path: Path,
    cli_env_path: Optional[Path],
) -> UploadLimits:
    """Priority: local .env < process environment < --env-file."""
    merged: dict[str, str] = {}
    merged.update(load_dotenv_file(dotenv_path))
    for key in _LIMIT_KEYS:
        if key in os.environ and os.environ[key] != "":
            merged[key] = os.environ[key]
    if cli_env_path is not None:
        if not cli_env_path.is_file():
            raise FileNotFoundError(f"Env file not found: {cli_env_path}")
        merged.update(load_dotenv_file(cli_env_path))

    missing = [k for k in _LIMIT_KEYS if k not in merged or merged[k] == ""]
    if missing:
        raise ValueError(
            "Upload limits not configured (need positive integers): "
            + ", ".join(missing)
        )

    max_kb = _parse_positive_int("MAX_UPLOAD_KB", merged["MAX_UPLOAD_KB"])
    max_total = _parse_positive_int(
        "MAX_UPLOAD_TOTAL_BYTES", merged["MAX_UPLOAD_TOTAL_BYTES"]
    )
    max_count = _parse_positive_int(
        "MAX_UPLOAD_FILE_COUNT", merged["MAX_UPLOAD_FILE_COUNT"]
    )
    return UploadLimits(
        max_file_bytes=max_kb * 1024,
        max_batch_bytes=max_total,
        max_batch_files=max_count,
    )


def detect_image_mime(path: Path) -> Optional[str]:
    guessed, _ = mimetypes.guess_type(str(path))
    if guessed and guessed.startswith("image/"):
        return guessed
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return None
    for magic, mime in _IMAGE_MAGIC:
        if head.startswith(magic):
            return mime
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _expand_pattern(pattern: str) -> list[Path]:
    pattern = pattern.strip()
    if not pattern:
        return []
    if pattern.startswith("re:"):
        regex = re.compile(pattern[3:])
        root = Path.cwd()
        found: list[Path] = []
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                p = Path(dirpath) / name
                try:
                    resolved = p.resolve()
                except OSError:
                    continue
                if regex.search(str(resolved)) or regex.search(str(p)):
                    found.append(resolved)
        return found
    matches = [Path(p) for p in glob.iglob(pattern, recursive=True)]
    return [p.resolve() for p in matches if p.is_file()]


def collect_paths_from_patterns(patterns: Sequence[str]) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    for pattern in patterns:
        for path in _expand_pattern(pattern):
            if path not in seen:
                seen.add(path)
                ordered.append(path)
    return ordered


def read_pattern_lines(stream: TextIO) -> list[str]:
    return [line.strip() for line in stream if line.strip() and not line.strip().startswith("#")]


def load_ignore_paths(ignore_file: Optional[Path]) -> set[Path]:
    if ignore_file is None:
        return set()
    if not ignore_file.is_file():
        raise FileNotFoundError(f"Ignore file not found: {ignore_file}")
    out: set[Path] = set()
    for line in ignore_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.add(Path(line).expanduser().resolve())
    return out


def prepare_files(
    paths: Sequence[Path],
    limits: UploadLimits,
    ignore: set[Path],
) -> BatchPlan:
    rejected_size: list[tuple[Path, str]] = []
    skipped_mime: list[Path] = []
    eligible: list[PreparedFile] = []

    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved in ignore:
            continue
        if not resolved.is_file():
            continue
        try:
            size = resolved.stat().st_size
        except OSError as exc:
            rejected_size.append((resolved, f"cannot read file: {exc}"))
            continue
        if size > limits.max_file_bytes:
            rejected_size.append(
                (
                    resolved,
                    f"exceeds per-file limit {limits.max_file_bytes} bytes (size {size})",
                )
            )
            continue
        mime = detect_image_mime(resolved)
        if not mime:
            skipped_mime.append(resolved)
            continue
        eligible.append(PreparedFile(path=resolved, size=size, mime=mime))

    eligible.sort(key=lambda item: item.size)
    batches: list[list[PreparedFile]] = []
    current: list[PreparedFile] = []
    current_bytes = 0

    for item in eligible:
        if item.size > limits.max_file_bytes:
            continue
        if current and (
            len(current) >= limits.max_batch_files
            or current_bytes + item.size > limits.max_batch_bytes
        ):
            batches.append(current)
            current = []
            current_bytes = 0
        current.append(item)
        current_bytes += item.size
    if current:
        batches.append(current)

    return BatchPlan(
        batches=batches,
        rejected_size=rejected_size,
        skipped_mime=skipped_mime,
    )


def default_log_path() -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Path(f"/tmp/image-store-batch-upload-{stamp}-{uuid.uuid4().hex[:8]}.log")


class OperationLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = path.open("a", encoding="utf-8")

    def log(self, message: str) -> None:
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n"
        self._file.write(line)
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def _encode_multipart(
    fields: dict[str, Any],
    files: Sequence[tuple[str, str, bytes]],
) -> tuple[bytes, str]:
    boundary = f"----batch-upload-{uuid.uuid4().hex}"
    lines: list[bytes] = []

    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, list):
            for item in value:
                lines.append(f"--{boundary}\r\n".encode())
                lines.append(
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
                )
                lines.append(f"{item}\r\n".encode())
        else:
            lines.append(f"--{boundary}\r\n".encode())
            lines.append(
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
            )
            lines.append(f"{value}\r\n".encode())

    for field_name, filename, data in files:
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{filename}"\r\n'
            ).encode()
        )
        lines.append(b"Content-Type: application/octet-stream\r\n\r\n")
        lines.append(data)
        lines.append(b"\r\n")

    lines.append(f"--{boundary}--\r\n".encode())
    body = b"".join(lines)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


@dataclass
class FileUploadOutcome:
    item: PreparedFile
    ok: bool
    message: str


def upload_batch(
    api_url: str,
    batch: Sequence[PreparedFile],
    metadata: dict[str, Any],
    timeout: float = 300.0,
) -> list[FileUploadOutcome]:
    file_payloads: list[tuple[str, str, bytes]] = []
    for item in batch:
        file_payloads.append(("files", item.path.name, item.path.read_bytes()))

    fields = {
        "sharing": metadata["sharing"],
        "source": metadata.get("source") or "",
        "license": metadata["license"],
        "tags": metadata.get("tags") or "",
        "categories": metadata.get("categories") or ["General"],
    }
    body, content_type = _encode_multipart(fields, file_payloads)
    req = urllib.request.Request(
        api_url,
        data=body,
        method="POST",
        headers={"Content-Type": content_type, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(detail)
        except json.JSONDecodeError:
            payload = {"error": detail or exc.reason, "details": []}
        message = payload.get("error", "Upload failed")
        errors = payload.get("details") or payload.get("errors") or []
        if not errors:
            errors = [
                {"file": item.path.name, "error": message} for item in batch
            ]
        return _outcomes_from_errors(batch, errors)
    except urllib.error.URLError as exc:
        errors = [{"file": item.path.name, "error": str(exc.reason)} for item in batch]
        return _outcomes_from_errors(batch, errors)

    image_ids = payload.get("image_ids") or []
    errors = payload.get("errors") or payload.get("details") or []
    errors_by_name = {e.get("file"): e.get("error", "upload failed") for e in errors}
    id_queue = list(image_ids)
    outcomes: list[FileUploadOutcome] = []
    for item in batch:
        if item.path.name in errors_by_name:
            outcomes.append(
                FileUploadOutcome(
                    item=item,
                    ok=False,
                    message=str(errors_by_name[item.path.name]),
                )
            )
        elif id_queue:
            id_queue.pop(0)
            outcomes.append(FileUploadOutcome(item=item, ok=True, message=""))
        else:
            outcomes.append(
                FileUploadOutcome(
                    item=item,
                    ok=False,
                    message="No image id in server response",
                )
            )
    return outcomes


def _outcomes_from_errors(
    batch: Sequence[PreparedFile],
    errors: list[dict[str, str]],
) -> list[FileUploadOutcome]:
    errors_by_name = {e.get("file"): e.get("error", "upload failed") for e in errors}
    outcomes: list[FileUploadOutcome] = []
    for item in batch:
        if item.path.name in errors_by_name:
            outcomes.append(
                FileUploadOutcome(
                    item=item,
                    ok=False,
                    message=str(errors_by_name[item.path.name]),
                )
            )
        else:
            outcomes.append(
                FileUploadOutcome(item=item, ok=False, message="Upload failed")
            )
    return outcomes


def _progress_line(
    processed_files: int,
    total_files: int,
    processed_bytes: int,
    total_bytes: int,
) -> str:
    pct = (100.0 * processed_bytes / total_bytes) if total_bytes else 100.0
    return f" [{processed_files}/{total_files} files, {pct:.1f}% bytes]"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upload_batch",
        description=(
            "Upload many image files to Image Store in batches respecting "
            "server size limits from .env / environment."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Pattern sources (exactly one required):\n"
            "  -g/--glob may be repeated; -F/--patterns-file lists one pattern per line\n"
            "  (use -F - for stdin; not combinable with -g).\n"
            "Patterns are glob paths (recursive with **). Prefix a pattern with re: for regex.\n"
            "\n"
            "Upload limits (all required, positive integers):\n"
            "  MAX_UPLOAD_KB, MAX_UPLOAD_TOTAL_BYTES, MAX_UPLOAD_FILE_COUNT\n"
            "  Loaded from ./.env, overridden by environment, then --env-file.\n"
            "\n"
            "Examples:\n"
            "  %(prog)s -g 'photos/**/*.jpg' --sharing public --license 'Public Domain' "
            "--source 'me'\n"
            "  %(prog)s -F patterns.txt --ignore-file uploaded.txt --brief "
            "--host 192.168.1.10:5000\n"
        ),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1:5000",
        metavar="HOST:PORT",
        help="Image Store host and port (default: 127.0.0.1:5000)",
    )
    parser.add_argument(
        "-g",
        "--glob",
        dest="globs",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Glob or re: regex pattern for image paths (repeatable)",
    )
    parser.add_argument(
        "-F",
        "--patterns-file",
        type=Path,
        metavar="FILE",
        help="Pattern list file, or - to read patterns from stdin (one per line)",
    )
    parser.add_argument(
        "-I",
        "--ignore-file",
        type=Path,
        metavar="FILE",
        help="Text file of absolute/relative paths to skip",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        metavar="FILE",
        help="Highest-priority .env file for upload limit variables",
    )
    parser.add_argument(
        "--dotenv",
        type=Path,
        default=Path(".env"),
        metavar="FILE",
        help="Base .env for limits (default: ./.env)",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        metavar="FILE",
        help="Operation log path (default: file under /tmp)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List eligible files and batch plan without uploading",
    )
    parser.add_argument(
        "--brief",
        action="store_true",
        help="Only print final statistics (no per-file lines or progress)",
    )
    parser.add_argument(
        "--sharing",
        required=True,
        choices=("public", "shared", "private"),
        help="Sharing for all uploads (required)",
    )
    parser.add_argument(
        "--license",
        required=True,
        metavar="NAME",
        help="License dictionary key for all uploads (required)",
    )
    parser.add_argument(
        "--source",
        default="",
        help="Source attribution (required when --sharing public)",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=["General"],
        metavar="CAT",
        help="Category keys (default: General)",
    )
    parser.add_argument(
        "--tags",
        default="",
        help="Optional comma-separated tags for all uploads",
    )
    return parser


def patterns_file_is_stdin(path: Optional[Path]) -> bool:
    return path is not None and str(path) == "-"


def read_patterns_from_stdin() -> list[str]:
    if sys.stdin.isatty():
        raise SystemExit("error: -F - requires piped stdin (stdin is a TTY)")
    return read_pattern_lines(sys.stdin)


def _gather_patterns(args: argparse.Namespace) -> list[str]:
    cli_patterns = list(args.globs)
    if patterns_file_is_stdin(args.patterns_file) and cli_patterns:
        raise SystemExit("error: -F - cannot be combined with -g/--glob")

    patterns: list[str] = []
    if patterns_file_is_stdin(args.patterns_file):
        patterns.extend(read_patterns_from_stdin())
    else:
        patterns.extend(cli_patterns)
        if args.patterns_file is not None:
            if not args.patterns_file.is_file():
                raise SystemExit(
                    f"error: patterns file not found: {args.patterns_file}"
                )
            patterns.extend(
                read_pattern_lines(
                    args.patterns_file.read_text(encoding="utf-8").splitlines()
                )
            )

    if not patterns:
        raise SystemExit(
            "error: no path patterns; use -g/--glob or -F/--patterns-file (- for stdin)"
        )
    return patterns


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.sharing == "public" and not args.source.strip():
        parser.error("--source is required when --sharing is public")

    try:
        limits = resolve_upload_limits(
            dotenv_path=args.dotenv,
            cli_env_path=args.env_file,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    patterns = _gather_patterns(args)
    try:
        ignore = load_ignore_paths(args.ignore_file)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    paths = collect_paths_from_patterns(patterns)
    plan = prepare_files(paths, limits, ignore)

    for path, reason in plan.rejected_size:
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        print(
            f"REJECT {path}: {reason}; limit={limits.max_file_bytes} bytes size={size}",
            file=sys.stderr,
        )

    log_path = args.log_file or default_log_path()
    logger = OperationLogger(log_path)
    logger.log(f"START patterns={patterns!r} dry_run={args.dry_run} brief={args.brief}")
    for p in plan.skipped_mime:
        logger.log(f"SKIP mime {p}")
    for path, reason in plan.rejected_size:
        logger.log(f"REJECT size {path}: {reason}")

    eligible = [item for batch in plan.batches for item in batch]
    total_files = len(eligible)
    total_bytes = sum(item.size for item in eligible)

    logger.log(
        f"PLAN files={total_files} bytes={total_bytes} batches={len(plan.batches)}"
    )

    if args.dry_run:
        print(f"dry-run: {total_files} file(s), {total_bytes} byte(s), "
              f"{len(plan.batches)} batch(es)")
        for i, batch in enumerate(plan.batches, 1):
            batch_bytes = sum(x.size for x in batch)
            print(f"  batch {i}: {len(batch)} file(s), {batch_bytes} byte(s)")
            for item in batch:
                print(f"    {item.path} ({item.size} bytes, {item.mime})")
        print(f"log file: {log_path}")
        logger.log("END dry-run")
        logger.close()
        return 0

    host = args.host.strip()
    if "://" not in host:
        base = f"http://{host}"
    else:
        base = host
    api_url = urllib.parse.urljoin(base.rstrip("/") + "/", "api/upload")

    metadata = {
        "sharing": args.sharing,
        "license": args.license,
        "source": args.source,
        "categories": args.categories,
        "tags": args.tags,
    }

    processed_files = 0
    processed_bytes = 0
    success_count = 0
    fail_count = 0
    uploaded_bytes = 0

    for batch_idx, batch in enumerate(plan.batches, 1):
        logger.log(f"BATCH {batch_idx} size={len(batch)}")
        if not args.brief:
            print(
                f"Uploading batch {batch_idx}/{len(plan.batches)} "
                f"({len(batch)} file(s))…",
                file=sys.stderr,
            )
        outcomes = upload_batch(api_url, batch, metadata)
        for outcome in outcomes:
            item = outcome.item
            processed_files += 1
            processed_bytes += item.size
            progress = _progress_line(
                processed_files, total_files, processed_bytes, total_bytes
            )
            if outcome.ok:
                success_count += 1
                uploaded_bytes += item.size
                logger.log(f"OK {item.path}")
                if not args.brief:
                    print(f"{item.path}{progress}")
            else:
                fail_count += 1
                logger.log(f"FAIL {item.path}: {outcome.message}")
                if not args.brief:
                    print(
                        f"FAIL {item.path}{progress}: {outcome.message}",
                        file=sys.stderr,
                    )

    print(
        f"done: uploaded={success_count} failed={fail_count} "
        f"bytes_uploaded={uploaded_bytes} total_eligible_files={total_files} "
        f"total_eligible_bytes={total_bytes}"
    )
    print(f"log file: {log_path}")
    logger.log(
        f"END uploaded={success_count} failed={fail_count} bytes={uploaded_bytes}"
    )
    logger.close()
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
