#!/usr/bin/env python3
"""Batch upload images to Image Store POST /api/upload."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import queue
import re
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any, Callable, Iterable, Iterator, Optional, Sequence, TextIO

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

_QUEUE_SENTINEL = object()
DEFAULT_UPLOAD_TIMEOUT_SEC = 30.0


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


@dataclass
class IgnoreRules:
    """Paths and directories to skip (-I); directories prune os.walk descent."""

    file_paths: set[Path] = field(default_factory=set)
    dir_paths: set[Path] = field(default_factory=set)

    def add(self, path: Path) -> None:
        resolved = path.expanduser().resolve()
        if resolved.is_dir():
            self.dir_paths.add(resolved)
        else:
            self.file_paths.add(resolved)

    def merge(self, other: IgnoreRules) -> None:
        self.file_paths |= other.file_paths
        self.dir_paths |= other.dir_paths


def _parse_positive_float(name: str, raw: str) -> float:
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a positive number, got: {raw!r}")
    if value <= 0:
        raise ValueError(f"{name} must be a positive number, got: {value}")
    return value


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


def glob_pattern_is_absolute(pattern: str) -> bool:
    """True when the glob is rooted (e.g. /var/photos/**/*.jpg on Unix)."""
    if pattern.startswith("/"):
        return True
    if os.name == "nt" and len(pattern) > 1 and pattern[1] == ":":
        return True
    return bool(PurePath(pattern).anchor)


def resolve_glob_pattern(pattern: str, pattern_root: Path) -> str:
    """Leave absolute globs unchanged; anchor relative globs under pattern_root."""
    if glob_pattern_is_absolute(pattern):
        return pattern
    return str((pattern_root / pattern).as_posix())


def normalize_glob_pattern_path(glob_pattern: str) -> str:
    """Collapse ``.`` / ``..`` in a glob path so it matches ``Path.resolve()`` strings."""
    if not glob_pattern:
        return glob_pattern
    stack: list[str] = []
    for seg in glob_pattern.replace("\\", "/").split("/"):
        if seg == "":
            if not stack:
                stack.append("")
            continue
        if seg == ".":
            continue
        if seg == "..":
            if stack and stack[0] == "":
                if len(stack) > 1:
                    stack.pop()
            elif stack:
                stack.pop()
            else:
                stack.append("..")
            continue
        stack.append(seg)
    if not stack:
        return ""
    if stack[0] == "":
        return "/" + "/".join(stack[1:])
    return "/".join(stack)


def glob_to_regex(glob_pattern: str) -> re.Pattern[str]:
    """Convert a glob path to a regex matching the full normalized path string."""
    glob_pattern = normalize_glob_pattern_path(glob_pattern)
    i = 0
    n = len(glob_pattern)
    parts: list[str] = ["^"]
    while i < n:
        if glob_pattern[i : i + 2] == "**":
            parts.append(".*")
            i += 2
            if i < n and glob_pattern[i] == "/":
                parts.append("/?")
                i += 1
            continue
        ch = glob_pattern[i]
        if ch == "*":
            parts.append("[^/]*")
        elif ch == "?":
            parts.append("[^/]")
        else:
            parts.append(re.escape(ch))
        i += 1
    parts.append("$")
    return re.compile("".join(parts))


def walk_root_for_glob(glob_pattern: str, pattern_root: Path) -> Path:
    glob_pattern = normalize_glob_pattern_path(glob_pattern)
    parts: list[str] = []
    for part in PurePath(glob_pattern).parts:
        if any(c in part for c in "*?") or part == "**":
            break
        parts.append(part)
    if not parts:
        return pattern_root.resolve()
    candidate = Path(*parts)
    if not candidate.is_absolute():
        candidate = pattern_root / candidate
    return candidate.resolve()


def path_is_ignored(path: Path, rules: IgnoreRules) -> bool:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return False
    if resolved in rules.file_paths:
        return True
    for directory in rules.dir_paths:
        try:
            resolved.relative_to(directory)
            return True
        except ValueError:
            continue
    return False


def dir_is_ignored(dir_path: Path, rules: IgnoreRules) -> bool:
    try:
        resolved = dir_path.expanduser().resolve()
    except OSError:
        return True
    if resolved in rules.dir_paths:
        return True
    for directory in rules.dir_paths:
        try:
            resolved.relative_to(directory)
            return True
        except ValueError:
            continue
    return False


def iter_glob_matches(
    pattern: str,
    pattern_root: Path,
    rules: IgnoreRules,
    on_dir_complete: Optional[Callable[[Path], None]] = None,
    interrupt: Optional[threading.Event] = None,
) -> Iterator[Path]:
    """Walk the filesystem and yield files matching a glob or re: pattern."""
    pattern = pattern.strip()
    if not pattern:
        return
    if pattern.startswith("re:"):
        regex = re.compile(pattern[3:])
        root = pattern_root.resolve()
    else:
        glob_pattern = resolve_glob_pattern(pattern, pattern_root)
        regex = glob_to_regex(glob_pattern)
        root = walk_root_for_glob(glob_pattern, pattern_root)

    if not root.is_dir():
        return

    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        if interrupt is not None and interrupt.is_set():
            return
        current = Path(dirpath)
        if dir_is_ignored(current, rules):
            dirnames[:] = []
            continue

        dirnames[:] = [
            d
            for d in dirnames
            if not dir_is_ignored(current / d, rules)
        ]

        for name in filenames:
            if interrupt is not None and interrupt.is_set():
                return
            p = (current / name).resolve()
            if path_is_ignored(p, rules):
                continue
            path_str = str(p)
            if regex.fullmatch(path_str) or regex.search(path_str):
                if p.is_file():
                    yield p

        if on_dir_complete is not None:
            on_dir_complete(current.resolve())


def collect_paths_from_patterns(
    patterns: Sequence[str],
    *,
    pattern_root: Optional[Path] = None,
    rules: Optional[IgnoreRules] = None,
) -> list[Path]:
    root = (pattern_root or Path.cwd()).resolve()
    ignore = rules or IgnoreRules()
    seen: set[Path] = set()
    ordered: list[Path] = []
    for pattern in patterns:
        for path in iter_glob_matches(pattern, root, ignore):
            if path not in seen:
                seen.add(path)
                ordered.append(path)
    return ordered


def read_path_lines(stream: TextIO) -> list[str]:
    return [
        line.strip()
        for line in stream
        if line.strip() and not line.strip().startswith("#")
    ]


def load_ignore_rules(ignore_file: Optional[Path]) -> IgnoreRules:
    rules = IgnoreRules()
    if ignore_file is None:
        return rules
    if not ignore_file.is_file():
        raise FileNotFoundError(f"Ignore file not found: {ignore_file}")
    for line in ignore_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rules.add(Path(line))
    return rules


def prepare_files(
    paths: Sequence[Path],
    limits: UploadLimits,
    ignore: set[Path],
) -> BatchPlan:
    """Legacy synchronous planner (tests); ignore is a set of file paths only."""
    rules = IgnoreRules(file_paths=set(ignore))
    rejected_size: list[tuple[Path, str]] = []
    skipped_mime: list[Path] = []
    eligible: list[PreparedFile] = []

    for path in paths:
        resolved = path.expanduser().resolve()
        if path_is_ignored(resolved, rules):
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

    batches, residual = pack_batches(eligible, limits)
    if residual:
        batches.append(residual)

    return BatchPlan(
        batches=batches,
        rejected_size=rejected_size,
        skipped_mime=skipped_mime,
    )


def pack_batches(
    items: Sequence[PreparedFile],
    limits: UploadLimits,
) -> tuple[list[list[PreparedFile]], list[PreparedFile]]:
    """Sort by size and split into full batches; trailing partial batch is residual."""
    sorted_items = sorted(items, key=lambda item: item.size)
    complete: list[list[PreparedFile]] = []
    current: list[PreparedFile] = []
    current_bytes = 0

    for item in sorted_items:
        if current and (
            len(current) >= limits.max_batch_files
            or current_bytes + item.size > limits.max_batch_bytes
        ):
            complete.append(current)
            current = []
            current_bytes = 0
        current.append(item)
        current_bytes += item.size

    return complete, current


def residual_should_wait(
    residual: Sequence[PreparedFile],
    limits: UploadLimits,
    more_items_expected: bool,
) -> bool:
    if not residual or not more_items_expected:
        return False
    total_bytes = sum(item.size for item in residual)
    return (
        len(residual) < limits.max_batch_files
        and total_bytes < limits.max_batch_bytes
    )


def try_prepare_file(
    path: Path,
    limits: UploadLimits,
) -> tuple[Optional[PreparedFile], Optional[str]]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, f"cannot read file: {exc}"
    if size > limits.max_file_bytes:
        return (
            None,
            f"exceeds per-file limit {limits.max_file_bytes} bytes (size {size})",
        )
    mime = detect_image_mime(path)
    if not mime:
        return None, "not an image"
    return PreparedFile(path=path, size=size, mime=mime), None


def default_log_path() -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Path(f"/tmp/image-store-batch-upload-{stamp}-{uuid.uuid4().hex[:8]}.log")


class OperationLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = path.open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def log(self, message: str) -> None:
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n"
        with self._lock:
            self._file.write(line)
            self._file.flush()

    def close(self) -> None:
        self._file.close()


@contextmanager
def block_sigint_in_thread():
    if not hasattr(signal, "pthread_sigmask"):
        yield
        return
    signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT})
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, {signal.SIGINT})


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
    timeout: float = DEFAULT_UPLOAD_TIMEOUT_SEC,
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
    processed_bytes: int,
    total_files: Optional[int],
    total_bytes: Optional[int],
) -> str:
    if total_files and total_bytes:
        pct = (100.0 * processed_bytes / total_bytes) if total_bytes else 100.0
        return f" [{processed_files}/{total_files} files, {pct:.1f}% bytes]"
    return f" [{processed_files} files processed]"


def _restart_hint(log_path: Path) -> str:
    return (
        "To resume after interruption, build a paths list for -F/--paths-list "
        "(ENQUEUE/LIST lines) and an ignore path list for -I/--ignore-file "
        f"(SCAN_DIR_COMPLETE and SKIP lines) from the log file: {log_path}"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upload_batch",
        description=(
            "Upload many image files to Image Store in batches respecting "
            "server size limits from .env / environment."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Input sources (at least one required):\n"
            "  -F/--paths-list — one image file path per line (use -F - for stdin);\n"
            "  -g/--glob — glob or re: pattern for directory scan (repeatable).\n"
            "  With both, -F paths are uploaded first; those paths are ignored during -g scan.\n"
            "  Folder scan runs only when -g is given.\n"
            "\n"
            "Upload limits (all required, positive integers):\n"
            "  MAX_UPLOAD_KB, MAX_UPLOAD_TOTAL_BYTES, MAX_UPLOAD_FILE_COUNT\n"
            "  Loaded from ./.env, overridden by environment, then --env-file.\n"
            "\n"
            "Examples:\n"
            "  %(prog)s -g 'photos/**/*.jpg' --sharing public --license 'Public Domain' "
            "--source 'me'\n"
            "  %(prog)s -F paths.txt -I uploaded.txt --brief --host 192.168.1.10:5000\n"
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
        help="Glob or re: regex pattern; scans directories (repeatable)",
    )
    parser.add_argument(
        "-F",
        "--paths-list",
        type=Path,
        metavar="FILE",
        help="Image paths file, or - to read paths from stdin (one per line)",
    )
    parser.add_argument(
        "-I",
        "--ignore-file",
        type=Path,
        metavar="FILE",
        help="Paths or directories to skip (one per line)",
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
        "--upload-timeout",
        type=float,
        default=DEFAULT_UPLOAD_TIMEOUT_SEC,
        metavar="SEC",
        help=(
            "HTTP response timeout per POST /api/upload batch "
            f"(default: {DEFAULT_UPLOAD_TIMEOUT_SEC:g} seconds)"
        ),
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
        help="License dictionary key (see enums.yml in the repo for valid values)",
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
        help="Category keys (valid values in enums.yml; default: General)",
    )
    parser.add_argument(
        "--tags",
        default="",
        help="Optional comma-separated tags for all uploads",
    )
    return parser


def paths_list_is_stdin(path: Optional[Path]) -> bool:
    return path is not None and str(path) == "-"


def read_paths_list_from_stdin() -> list[str]:
    if sys.stdin.isatty():
        raise SystemExit("error: -F - requires piped stdin (stdin is a TTY)")
    return read_path_lines(sys.stdin)


def _gather_paths_list(args: argparse.Namespace) -> list[str]:
    if paths_list_is_stdin(args.paths_list):
        return read_paths_list_from_stdin()
    if args.paths_list is None:
        return []
    if not args.paths_list.is_file():
        raise SystemExit(f"error: paths list file not found: {args.paths_list}")
    return read_path_lines(
        args.paths_list.read_text(encoding="utf-8").splitlines()
    )


def _enqueue_path(
    path: Path,
    limits: UploadLimits,
    rules: IgnoreRules,
    work_queue: queue.Queue,
    logger: OperationLogger,
    seen: set[Path],
) -> None:
    try:
        resolved = path.expanduser().resolve()
    except OSError as exc:
        logger.log(f"SKIP path {path}: {exc}")
        return
    if resolved in seen:
        return
    if path_is_ignored(resolved, rules):
        logger.log(f"SKIP ignore {resolved}")
        return
    if not resolved.is_file():
        logger.log(f"SKIP not-file {resolved}")
        return
    prepared, reason = try_prepare_file(resolved, limits)
    if prepared is None:
        if reason == "not an image":
            logger.log(f"SKIP mime {resolved}")
        else:
            logger.log(f"REJECT size {resolved}: {reason}")
        return
    seen.add(resolved)
    work_queue.put(prepared)
    logger.log(f"ENQUEUE {resolved} size={prepared.size}")


def _producer(
    *,
    paths_list: Sequence[str],
    globs: Sequence[str],
    limits: UploadLimits,
    ignore_rules: IgnoreRules,
    pattern_root: Path,
    work_queue: queue.Queue,
    logger: OperationLogger,
    seen: set[Path],
    scan_ignore: IgnoreRules,
    interrupt: threading.Event,
) -> None:
    for raw in paths_list:
        if interrupt.is_set():
            break
        logger.log(f"LIST {raw}")
        try:
            path = Path(raw).expanduser()
        except Exception as exc:
            logger.log(f"SKIP path {raw}: {exc}")
            continue
        _enqueue_path(path, limits, ignore_rules, work_queue, logger, seen)
        try:
            resolved = path.resolve()
            if resolved.is_file():
                scan_ignore.file_paths.add(resolved)
        except OSError:
            pass

    if globs and not interrupt.is_set():
        def on_dir_complete(directory: Path) -> None:
            if not dir_is_ignored(directory, ignore_rules):
                logger.log(f"SCAN_DIR_COMPLETE {directory}")

        for pattern in globs:
            if interrupt.is_set():
                break
            logger.log(f"GLOB {pattern}")
            for file_path in iter_glob_matches(
                pattern,
                pattern_root,
                scan_ignore,
                on_dir_complete=on_dir_complete,
                interrupt=interrupt,
            ):
                if interrupt.is_set():
                    break
                _enqueue_path(
                    file_path,
                    limits,
                    ignore_rules,
                    work_queue,
                    logger,
                    seen,
                )


def _upload_one_batch(
    batch: Sequence[PreparedFile],
    *,
    api_url: str,
    metadata: dict[str, Any],
    upload_timeout: float,
    dry_run: bool,
    brief: bool,
    logger: OperationLogger,
    stats: dict[str, int],
) -> None:
    if dry_run:
        batch_bytes = sum(x.size for x in batch)
        logger.log(f"DRY_BATCH size={len(batch)} bytes={batch_bytes}")
        for item in batch:
            stats["processed"] += 1
            stats["success"] += 1
            stats["bytes"] += item.size
            logger.log(f"OK {item.path}")
        return

    logger.log(f"BATCH size={len(batch)}")
    if not brief:
        print(f"Uploading batch ({len(batch)} file(s))…", file=sys.stderr)
    with block_sigint_in_thread():
        outcomes = upload_batch(
            api_url, batch, metadata, timeout=upload_timeout
        )
    for outcome in outcomes:
        item = outcome.item
        stats["processed"] += 1
        progress = _progress_line(stats["processed"], stats["bytes"], None, None)
        if outcome.ok:
            stats["success"] += 1
            stats["bytes"] += item.size
            logger.log(f"OK {item.path}")
            if not brief:
                print(f"{item.path}{progress}")
        else:
            stats["fail"] += 1
            logger.log(f"FAIL {item.path}: {outcome.message}")
            if not brief:
                print(
                    f"FAIL {item.path}{progress}: {outcome.message}",
                    file=sys.stderr,
                )


def _drain_work_queue(
    work_queue: queue.Queue,
    max_items: int,
    producer_done: threading.Event,
) -> list[PreparedFile]:
    items: list[PreparedFile] = []
    while len(items) < max_items:
        if producer_done.is_set() and work_queue.empty():
            break
        try:
            item = work_queue.get(timeout=0.25)
        except queue.Empty:
            if producer_done.is_set():
                break
            continue
        if item is _QUEUE_SENTINEL:
            continue
        items.append(item)
    while producer_done.is_set():
        try:
            item = work_queue.get_nowait()
        except queue.Empty:
            break
        if item is _QUEUE_SENTINEL:
            continue
        items.append(item)
        if len(items) >= max_items:
            break
    return items


def _consumer_upload_batches(
    *,
    work_queue: queue.Queue,
    limits: UploadLimits,
    logger: OperationLogger,
    api_url: str,
    metadata: dict[str, Any],
    upload_timeout: float,
    dry_run: bool,
    brief: bool,
    interrupt: threading.Event,
    stats: dict[str, int],
    producer_done: threading.Event,
) -> None:
    residual: list[PreparedFile] = []
    dequeue_limit = 10 * limits.max_batch_files

    while True:
        if producer_done.is_set() and work_queue.empty() and not residual:
            break
        if interrupt.is_set() and producer_done.is_set() and work_queue.empty():
            if residual:
                _upload_one_batch(
                    residual,
                    api_url=api_url,
                    metadata=metadata,
                    upload_timeout=upload_timeout,
                    dry_run=dry_run,
                    brief=brief,
                    logger=logger,
                    stats=stats,
                )
                residual = []
            break

        if (
            work_queue.qsize() < dequeue_limit
            and not producer_done.is_set()
        ):
            time.sleep(0.05)
            continue

        chunk = _drain_work_queue(work_queue, dequeue_limit, producer_done)
        if not chunk:
            if producer_done.is_set() and residual:
                _upload_one_batch(
                    residual,
                    api_url=api_url,
                    metadata=metadata,
                    upload_timeout=upload_timeout,
                    dry_run=dry_run,
                    brief=brief,
                    logger=logger,
                    stats=stats,
                )
                residual = []
            break

        to_pack = residual + chunk
        residual = []
        batches, trailing = pack_batches(to_pack, limits)
        more_expected = not producer_done.is_set() or not work_queue.empty()
        if residual_should_wait(trailing, limits, more_expected):
            residual = trailing
            upload_batches = batches
        else:
            if trailing:
                batches.append(trailing)
            upload_batches = batches

        for batch in upload_batches:
            if interrupt.is_set():
                break
            _upload_one_batch(
                batch,
                api_url=api_url,
                metadata=metadata,
                upload_timeout=upload_timeout,
                dry_run=dry_run,
                brief=brief,
                logger=logger,
                stats=stats,
            )

        if producer_done.is_set() and work_queue.empty() and residual:
            _upload_one_batch(
                residual,
                api_url=api_url,
                metadata=metadata,
                upload_timeout=upload_timeout,
                dry_run=dry_run,
                brief=brief,
                logger=logger,
                stats=stats,
            )
            residual = []

        if producer_done.is_set() and work_queue.empty() and not residual:
            break


def run_upload_pipeline(
    *,
    paths_list: Sequence[str],
    globs: Sequence[str],
    limits: UploadLimits,
    ignore_rules: IgnoreRules,
    logger: OperationLogger,
    api_url: str,
    metadata: dict[str, Any],
    dry_run: bool,
    brief: bool,
    interrupt: threading.Event,
    upload_timeout: float = DEFAULT_UPLOAD_TIMEOUT_SEC,
) -> dict[str, int]:
    work_queue: queue.Queue = queue.Queue()
    producer_done = threading.Event()
    seen: set[Path] = set()
    scan_ignore = IgnoreRules()
    scan_ignore.merge(ignore_rules)

    stats = {"processed": 0, "success": 0, "fail": 0, "bytes": 0, "enqueued": 0}

    def producer_wrapper() -> None:
        try:
            _producer(
                paths_list=paths_list,
                globs=globs,
                limits=limits,
                ignore_rules=ignore_rules,
                pattern_root=Path.cwd().resolve(),
                work_queue=work_queue,
                logger=logger,
                seen=seen,
                scan_ignore=scan_ignore,
                interrupt=interrupt,
            )
        finally:
            work_queue.put(_QUEUE_SENTINEL)
            producer_done.set()

    producer_thread = threading.Thread(target=producer_wrapper, name="producer")
    consumer_thread = threading.Thread(
        target=_consumer_upload_batches,
        kwargs={
            "work_queue": work_queue,
            "limits": limits,
            "logger": logger,
            "api_url": api_url,
            "metadata": metadata,
            "upload_timeout": upload_timeout,
            "dry_run": dry_run,
            "brief": brief,
            "interrupt": interrupt,
            "stats": stats,
            "producer_done": producer_done,
        },
        name="consumer",
    )
    producer_thread.start()
    consumer_thread.start()
    producer_thread.join()
    consumer_thread.join()
    return stats


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

    paths_list = _gather_paths_list(args)
    globs = list(args.globs)
    if not paths_list and not globs:
        raise SystemExit(
            "error: no inputs; use -F/--paths-list and/or -g/--glob"
        )

    try:
        ignore_rules = load_ignore_rules(args.ignore_file)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        upload_timeout = _parse_positive_float(
            "--upload-timeout", args.upload_timeout
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    log_path = args.log_file or default_log_path()
    logger = OperationLogger(log_path)
    logger.log(
        f"START paths_list={len(paths_list)} globs={globs!r} "
        f"dry_run={args.dry_run} brief={args.brief} "
        f"upload_timeout={upload_timeout}"
    )

    host = args.host.strip()
    base = host if "://" in host else f"http://{host}"
    api_url = urllib.parse.urljoin(base.rstrip("/") + "/", "api/upload")

    metadata = {
        "sharing": args.sharing,
        "license": args.license,
        "source": args.source,
        "categories": args.categories,
        "tags": args.tags,
    }

    interrupt = threading.Event()
    interrupted = False

    def on_sigint(signum, frame) -> None:
        nonlocal interrupted
        interrupted = True
        interrupt.set()
        print(
            "\nInterrupt received; finishing current upload if any…",
            file=sys.stderr,
        )

    signal.signal(signal.SIGINT, on_sigint)

    stats = run_upload_pipeline(
        paths_list=paths_list,
        globs=globs,
        limits=limits,
        ignore_rules=ignore_rules,
        logger=logger,
        api_url=api_url,
        metadata=metadata,
        dry_run=args.dry_run,
        brief=args.brief,
        interrupt=interrupt,
        upload_timeout=upload_timeout,
    )

    print(
        f"done: uploaded={stats['success']} failed={stats['fail']} "
        f"bytes_uploaded={stats['bytes']} files_processed={stats['processed']}"
    )
    print(f"log file: {log_path}")
    print(_restart_hint(log_path))
    logger.log(
        f"END uploaded={stats['success']} failed={stats['fail']} "
        f"bytes={stats['bytes']} interrupted={interrupted}"
    )
    logger.close()

    if interrupted:
        return 130
    return 0 if stats["fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
