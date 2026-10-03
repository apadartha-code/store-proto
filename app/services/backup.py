import shutil
import sqlite3
from pathlib import Path

from app.config import Config
from app.db import get_connection, write_lock


def backup_database() -> Path:
    """SQLite online backup under exclusive write lock."""
    Config.ensure_dirs()
    dest = Config.BACKUP_PATH

    with write_lock():
        source = get_connection()
        try:
            dest_conn = sqlite3.connect(dest)
            try:
                source.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            source.close()

    return dest


def safe_file_copy_backup() -> Path:
    """Fallback: copy under exclusive lock if backup API unavailable."""
    with write_lock():
        shutil.copy2(Config.DB_PATH, Config.BACKUP_PATH)
    return Config.BACKUP_PATH
