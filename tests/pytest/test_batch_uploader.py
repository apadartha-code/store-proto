"""Features.md §11 — batch-uploader sample client helpers."""

from __future__ import annotations

import os
import sys
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


def test_patterns_file_is_stdin():
    assert upload_batch.patterns_file_is_stdin(Path("-"))
    assert not upload_batch.patterns_file_is_stdin(Path("patterns.txt"))
    assert not upload_batch.patterns_file_is_stdin(None)


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
