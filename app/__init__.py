from flask import Flask

from app.config import Config
from app.db import init_db
from app.logging_config import setup_logging
from app.services.dictionary import get_dictionary


def create_app() -> Flask:
    setup_logging()
    Config.ensure_dirs()
    get_dictionary()
    init_db()

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = Config.MAX_UPLOAD_TOTAL_BYTES + (1024 * 1024)

    from app.routes.api import api_bp
    from app.routes.web import web_bp

    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(web_bp)

    @app.context_processor
    def inject_dictionary():
        dd = get_dictionary()
        return {
            "all_categories": [
                (key, dd.category_by_key(key)) for key in dd.category_keys()
            ],
            "all_licenses": [
                (key, dd.license_by_key(key)) for key in dd.license_keys()
            ],
        }

    return app
