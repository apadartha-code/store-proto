from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _reload_app_package() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]


@pytest.fixture
def storage_path(tmp_path: Path) -> Path:
    root = tmp_path / "storage"
    root.mkdir()
    return root


@pytest.fixture
def app(storage_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("MAX_UPLOAD_KB", "5000")
    monkeypatch.setenv("FRAGMENT_SIZE_KB", "64")
    _reload_app_package()
    import app.config as config_mod

    importlib.reload(config_mod)
    from app import create_app
    from app.config import Config

    Config.ensure_dirs()
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()
