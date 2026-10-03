import os
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


class Config:
    STORAGE_PATH = Path(os.environ.get("STORAGE_PATH", "/data")).resolve()
    FRAGMENT_SIZE_KB = _int_env("FRAGMENT_SIZE_KB", 64)
    LISTEN_PORT = _int_env("LISTEN_PORT", 5000)
    MAX_UPLOAD_KB = _int_env("MAX_UPLOAD_KB", 1000)
    CERT_PATH = os.environ.get("CERT_PATH") or None
    KEY_PATH = os.environ.get("KEY_PATH") or None

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    LOG_SYSLOG = os.environ.get("LOG_SYSLOG", "").lower() in ("1", "true", "yes", "on")
    LOG_SYSLOG_ADDRESS = os.environ.get("LOG_SYSLOG_ADDRESS", "/dev/log")

    DB_PATH = STORAGE_PATH / "store.db"
    THUMBNAILS_DIR = STORAGE_PATH / "thumbnails"
    FRAGMENTS_PUBLIC_DIR = STORAGE_PATH / "fragments" / "public"
    FRAGMENTS_USER_DIR = STORAGE_PATH / "fragments" / "user"
    BACKUP_PATH = STORAGE_PATH / "store.backup.db"

    PAGE_ROWS = 6
    PAGE_COLS = 10
    PAGE_SIZE = PAGE_ROWS * PAGE_COLS

    @classmethod
    def ensure_dirs(cls) -> None:
        cls.STORAGE_PATH.mkdir(parents=True, exist_ok=True)
        cls.THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)
        cls.FRAGMENTS_PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
        cls.FRAGMENTS_USER_DIR.mkdir(parents=True, exist_ok=True)
