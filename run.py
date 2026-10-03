#!/usr/bin/env python3
import os
import ssl
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    _env_file = os.environ.get("ENV_FILE")
    if _env_file:
        load_dotenv(_env_file)
    else:
        load_dotenv(Path(__file__).resolve().parent / ".env")

from app import create_app
from app.config import Config

app = create_app()


def main() -> None:
    Config.ensure_dirs()
    ssl_context = None
    if Config.CERT_PATH:
        key = Config.KEY_PATH or Config.CERT_PATH
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(Config.CERT_PATH, key)

    app.run(
        host="0.0.0.0",
        port=Config.LISTEN_PORT,
        debug=False,
        ssl_context=ssl_context,
    )


if __name__ == "__main__":
    main()
