from __future__ import annotations

import importlib
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from werkzeug.serving import make_server


def _reload_app_package() -> None:
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]
    from app.services.dictionary import reset_dictionary_cache

    reset_dictionary_cache()


@pytest.fixture(scope="session", autouse=True)
def live_app_server(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Fresh STORAGE_PATH and Flask on 127.0.0.1:5000 for UI tests."""
    storage = tmp_path_factory.mktemp("playwright_storage")
    os.environ["STORAGE_PATH"] = str(storage)
    os.environ["LISTEN_PORT"] = "5000"
    os.environ["MAX_UPLOAD_KB"] = "5000"
    os.environ["FRAGMENT_SIZE_KB"] = "64"
    _reload_app_package()
    import app.config as config_mod

    importlib.reload(config_mod)
    from app import create_app
    from app.config import Config

    Config.ensure_dirs()
    app = create_app()
    server = make_server("127.0.0.1", 5000, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = "http://127.0.0.1:5000/"
    for _ in range(100):
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    break
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.1)
    else:
        server.shutdown()
        pytest.fail("Flask server did not become ready on 127.0.0.1:5000")

    yield

    server.shutdown()
