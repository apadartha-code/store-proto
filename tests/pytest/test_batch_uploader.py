"""Features.md §11 — batch-uploader sample client helpers."""

from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_UPLOADER_DIR = _ROOT / "sample-clients" / "batch-uploader"
if str(_UPLOADER_DIR) not in sys.path:
    sys.path.insert(0, str(_UPLOADER_DIR))

import upload_batch  # noqa: E402


def test_resolve_upload_limits_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("MAX_UPLOAD_KB", raising=False)
    monkeypatch.delenv("MAX_UPLOAD_TOTAL_BYTES", raising=False)
    monkeypatch.delenv("MAX_UPLOAD_FILE_COUNT", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "MAX_UPLOAD_KB=100\nMAX_UPLOAD_TOTAL_BYTES=5000\nMAX_UPLOAD_FILE_COUNT=3\n",
        encoding="utf-8",
    )
    limits = upload_batch.resolve_upload_limits(dotenv_path=env, cli_env_path=None)
    assert limits.max_file_bytes == 100 * 1024
    assert limits.max_batch_bytes == 5000
    assert limits.max_batch_files == 3


def test_resolve_upload_limits_env_overrides_dotenv(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "MAX_UPLOAD_KB=10\nMAX_UPLOAD_TOTAL_BYTES=1000\nMAX_UPLOAD_FILE_COUNT=2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAX_UPLOAD_KB", "20")
    limits = upload_batch.resolve_upload_limits(dotenv_path=env, cli_env_path=None)
    assert limits.max_file_bytes == 20 * 1024


def test_resolve_upload_limits_cli_env_highest(tmp_path, monkeypatch):
    base = tmp_path / ".env"
    base.write_text(
        "MAX_UPLOAD_KB=1\nMAX_UPLOAD_TOTAL_BYTES=100\nMAX_UPLOAD_FILE_COUNT=1\n",
        encoding="utf-8",
    )
    override = tmp_path / "override.env"
    override.write_text(
        "MAX_UPLOAD_KB=5\nMAX_UPLOAD_TOTAL_BYTES=500\nMAX_UPLOAD_FILE_COUNT=5\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MAX_UPLOAD_KB", "9")
    limits = upload_batch.resolve_upload_limits(
        dotenv_path=base,
        cli_env_path=override,
    )
    assert limits.max_file_bytes == 5 * 1024
    assert limits.max_batch_files == 5


def test_resolve_upload_limits_missing_exits(tmp_path, monkeypatch):
    monkeypatch.delenv("MAX_UPLOAD_KB", raising=False)
    monkeypatch.delenv("MAX_UPLOAD_TOTAL_BYTES", raising=False)
    monkeypatch.delenv("MAX_UPLOAD_FILE_COUNT", raising=False)
    env = tmp_path / ".env"
    env.write_text("MAX_UPLOAD_KB=10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="MAX_UPLOAD_TOTAL_BYTES"):
        upload_batch.resolve_upload_limits(dotenv_path=env, cli_env_path=None)


def test_prepare_files_batches_by_size(tmp_path):
    limits = upload_batch.UploadLimits(
        max_file_bytes=100,
        max_batch_bytes=150,
        max_batch_files=10,
    )
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    c = tmp_path / "c.png"
    a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 40)
    b.write_bytes(b"\x89PNG\r\n\x1a\n" + b"y" * 60)
    c.write_bytes(b"\x89PNG\r\n\x1a\n" + b"z" * 50)

    plan = upload_batch.prepare_files([c, a, b], limits, set())
    assert len(plan.batches) == 2
    sizes = [sum(x.size for x in batch) for batch in plan.batches]
    assert all(s <= 150 for s in sizes)


def test_glob_pattern_is_absolute():
    assert upload_batch.glob_pattern_is_absolute("/var/data/**/*.jpg")
    assert not upload_batch.glob_pattern_is_absolute("data/**/*.jpg")


def test_collect_paths_relative_to_cwd(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    pic = data / "shot.png"
    pic.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 8)
    monkeypatch.chdir(tmp_path)
    paths = upload_batch.collect_paths_from_patterns(["data/*.png"])
    assert pic.resolve() in paths


def test_collect_paths_absolute_ignores_cwd(tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    pic = elsewhere / "abs.png"
    pic.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 8)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    pattern = str(elsewhere / "*.png")
    paths = upload_batch.collect_paths_from_patterns([pattern])
    assert pic.resolve() in paths


def test_upload_timeout_cli_default_and_override():
    # Features.md §11 — HTTP response timeout for POST /api/upload
    parser = upload_batch.build_arg_parser()
    base = ["--sharing", "private", "--license", "Public Domain", "-g", "*.png"]
    args = parser.parse_args(base)
    assert args.upload_timeout == upload_batch.DEFAULT_UPLOAD_TIMEOUT_SEC
    args = parser.parse_args([*base, "--upload-timeout", "120"])
    assert args.upload_timeout == 120.0


def test_paths_list_is_stdin():
    assert upload_batch.paths_list_is_stdin(Path("-"))
    assert not upload_batch.paths_list_is_stdin(Path("paths.txt"))
    assert not upload_batch.paths_list_is_stdin(None)


def test_paths_list_is_literal_not_glob(tmp_path, monkeypatch):
    # Features.md §11 — -F/--paths-list lines are filesystem paths, not -g patterns.
    data = tmp_path / "data"
    data.mkdir()
    pic = data / "real.png"
    pic.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 8)

    limits = upload_batch.UploadLimits(10000, 100000, 10)
    rules = upload_batch.IgnoreRules()
    seen: set[Path] = set()
    logger = upload_batch.OperationLogger(tmp_path / "op.log")
    monkeypatch.chdir(tmp_path)

    def enqueue_line(line: str) -> int:
        """Same path handling as producer: Path(raw), no glob/re expansion."""
        q: queue.Queue = queue.Queue()
        upload_batch._enqueue_path(
            Path(line), limits, rules, q, logger, seen
        )
        return q.qsize()

    # Positive: a real file path is enqueued once.
    assert enqueue_line(str(pic.resolve())) == 1

    # Negative (glob): if the line were interpreted as a glob, data/*.png would
    # match real.png and enqueue it again. Literal Path("data/*.png") is not a file.
    assert enqueue_line("data/*.png") == 0

    # Negative (re:): scan patterns use -g; a paths-list line must not walk the tree.
    assert enqueue_line("re:.*\\.png$") == 0

    # Negative (absolute glob-shaped string): still one path, not expansion.
    assert enqueue_line(str(data / "*.png")) == 0

    logger.close()


def test_paths_list_skips_ignored_image_path(tmp_path, monkeypatch):
    # Features.md §11 — -I applies to -F/--paths-list lines (same as -g scan).
    pic = tmp_path / "listed.png"
    pic.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 8)
    ignore = upload_batch.IgnoreRules()
    ignore.add(pic)

    limits = upload_batch.UploadLimits(10000, 100000, 10)
    seen: set[Path] = set()
    log_path = tmp_path / "ignore-path.log"
    logger = upload_batch.OperationLogger(log_path)
    q: queue.Queue = queue.Queue()
    monkeypatch.chdir(tmp_path)

    upload_batch._enqueue_path(
        pic, limits, ignore, q, logger, seen
    )

    assert q.empty()
    log_text = log_path.read_text(encoding="utf-8")
    assert f"SKIP ignore {pic.resolve()}" in log_text
    logger.close()


def test_paths_list_processed_before_glob_without_duplicates(
    tmp_path, monkeypatch
):
    # Features.md §11 — -F first; those paths are on scan_ignore so -g does not re-enqueue.
    data = tmp_path / "data"
    data.mkdir()
    pic = data / "dup.png"
    other = data / "other.png"
    pic.write_bytes(b"\x89PNG\r\n\x1a\n" + b"a" * 8)
    other.write_bytes(b"\x89PNG\r\n\x1a\n" + b"b" * 8)

    limits = upload_batch.UploadLimits(10000, 100000, 10)
    ignore = upload_batch.IgnoreRules()
    scan_ignore = upload_batch.IgnoreRules()
    scan_ignore.merge(ignore)
    seen: set[Path] = set()
    work_q: queue.Queue = queue.Queue()
    log_path = tmp_path / "dedup.log"
    logger = upload_batch.OperationLogger(log_path)
    monkeypatch.chdir(tmp_path)

    upload_batch._producer(
        paths_list=[str(pic.resolve())],
        globs=["data/*.png"],
        limits=limits,
        ignore_rules=ignore,
        pattern_root=tmp_path,
        work_queue=work_q,
        logger=logger,
        seen=seen,
        scan_ignore=scan_ignore,
        interrupt=threading.Event(),
    )

    enqueued = []
    while not work_q.empty():
        enqueued.append(work_q.get())

    paths = {item.path for item in enqueued}
    assert paths == {pic.resolve(), other.resolve()}
    assert len(enqueued) == 2

    log_text = log_path.read_text(encoding="utf-8")
    assert log_text.count(f"ENQUEUE {pic.resolve()}") == 1
    assert log_text.count(f"ENQUEUE {other.resolve()}") == 1
    logger.close()


def test_producer_stops_when_interrupt_set_before_paths_list(tmp_path):
    # Features.md §11 — producer exits immediately on interrupt (no in-flight API).
    pic = tmp_path / "skip-me.png"
    pic.write_bytes(b"\x89PNG\r\n\x1a\n")
    interrupt = threading.Event()
    interrupt.set()
    limits = upload_batch.UploadLimits(10000, 100000, 10)
    work_q: queue.Queue = queue.Queue()
    logger = upload_batch.OperationLogger(tmp_path / "prod-int.log")
    upload_batch._producer(
        paths_list=[str(pic)],
        globs=[],
        limits=limits,
        ignore_rules=upload_batch.IgnoreRules(),
        pattern_root=tmp_path,
        work_queue=work_q,
        logger=logger,
        seen=set(),
        scan_ignore=upload_batch.IgnoreRules(),
        interrupt=interrupt,
    )
    assert work_q.empty()
    logger.close()


def test_iter_glob_matches_stops_when_interrupt_set(tmp_path, monkeypatch):
    # Features.md §11 — glob walk stops as soon as interrupt is set.
    root = tmp_path / "many"
    root.mkdir()
    for i in range(20):
        (root / f"{i}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    interrupt = threading.Event()
    rules = upload_batch.IgnoreRules()
    monkeypatch.chdir(tmp_path)
    pattern = str(root / "*.png")
    found: list[Path] = []
    for path in upload_batch.iter_glob_matches(
        pattern, tmp_path, rules, interrupt=interrupt
    ):
        found.append(path)
        if len(found) == 3:
            interrupt.set()
    assert len(found) == 3
    assert len(list(upload_batch.iter_glob_matches(pattern, tmp_path, rules))) == 20


def test_ignore_directory_skips_scan(tmp_path, monkeypatch):
    root = tmp_path / "tree"
    skip = root / "skip"
    keep = root / "keep"
    skip.mkdir(parents=True)
    keep.mkdir(parents=True)
    skipped_pic = skip / "a.png"
    kept_pic = keep / "b.png"
    skipped_pic.write_bytes(b"\x89PNG\r\n\x1a\n")
    kept_pic.write_bytes(b"\x89PNG\r\n\x1a\n")
    rules = upload_batch.IgnoreRules()
    rules.add(skip)
    monkeypatch.chdir(tmp_path)
    pattern = str(root / "**" / "*.png")
    found = list(
        upload_batch.iter_glob_matches(pattern, tmp_path, rules)
    )
    assert kept_pic.resolve() in found
    assert skipped_pic.resolve() not in found


def test_residual_should_wait():
    limits = upload_batch.UploadLimits(
        max_file_bytes=1000,
        max_batch_bytes=1000,
        max_batch_files=10,
    )
    small = [
        upload_batch.PreparedFile(Path("a"), 10, "image/png"),
        upload_batch.PreparedFile(Path("b"), 10, "image/png"),
    ]
    assert upload_batch.residual_should_wait(small, limits, True)
    assert not upload_batch.residual_should_wait(small, limits, False)


def test_glob_to_regex_matches_resolved_path(tmp_path):
    pic = tmp_path / "data" / "x.png"
    pic.parent.mkdir(parents=True)
    pic.write_bytes(b"\x89PNG\r\n\x1a\n")
    pattern = str(tmp_path / "data" / "*.png")
    rx = upload_batch.glob_to_regex(pattern)
    assert rx.fullmatch(str(pic.resolve()))


def test_run_pipeline_paths_list_dry_run(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "MAX_UPLOAD_KB=100\nMAX_UPLOAD_TOTAL_BYTES=50000\nMAX_UPLOAD_FILE_COUNT=5\n",
        encoding="utf-8",
    )
    pic = tmp_path / "one.png"
    pic.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 4)
    log_path = tmp_path / "run.log"
    monkeypatch.chdir(tmp_path)
    limits = upload_batch.resolve_upload_limits(dotenv_path=env, cli_env_path=None)
    logger = upload_batch.OperationLogger(log_path)
    stats = upload_batch.run_upload_pipeline(
        paths_list=[str(pic)],
        globs=[],
        limits=limits,
        ignore_rules=upload_batch.IgnoreRules(),
        logger=logger,
        api_url="http://127.0.0.1/api/upload",
        metadata={"sharing": "private", "license": "Public Domain"},
        dry_run=True,
        brief=True,
        interrupt=__import__("threading").Event(),
    )
    logger.close()
    assert stats["success"] == 1
    text = log_path.read_text(encoding="utf-8")
    assert "ENQUEUE" in text
    assert "LIST" in text


def test_prepare_files_rejects_oversize(tmp_path):
    limits = upload_batch.UploadLimits(
        max_file_bytes=10,
        max_batch_bytes=1000,
        max_batch_files=10,
    )
    big = tmp_path / "big.png"
    big.write_bytes(b"\x89PNG\r\n\x1a\n" + b"z" * 50)
    plan = upload_batch.prepare_files([big], limits, set())
    assert len(plan.rejected_size) == 1
    assert plan.batches == []
