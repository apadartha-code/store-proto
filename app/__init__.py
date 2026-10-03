from flask import Flask

from app.config import Config
from app.db import init_db
from app.logging_config import setup_logging


def create_app() -> Flask:
    setup_logging()
    Config.ensure_dirs()
    init_db()

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = Config.MAX_UPLOAD_KB * 1024 * 20

    from app.routes.api import api_bp
    from app.routes.web import web_bp

    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(web_bp)

    return app
