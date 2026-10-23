# Image Store (v2)

LAN-hostable image gallery with fragment storage, nickname recall, and SQLite persistence.

**Capabilities and behavior:** [Features.md](Features.md)  
**Contributing / agents:** [AGENTS.md](AGENTS.md)

## Quick start

### Local (Python)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional: edit overrides
python run.py
```

Open `http://localhost:5000`.

### Docker

```bash
docker build -t image-store .
docker run --rm -p 5000:5000 -v image-store-data:/data image-store
```

Syslog on the host (Linux):

```bash
docker run --rm -p 5000:5000 \
  -v image-store-data:/data \
  -v /dev/log:/dev/log \
  -e LOG_SYSLOG=true \
  image-store
```

## Configuration

Settings use **environment variables** (see `.env.example`). Load a local `.env` automatically when running `python run.py` (`python-dotenv`).

| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_PATH` | `/data` | Root for DB, thumbnails, fragments |
| `FRAGMENT_SIZE_KB` | `64` | Fragment chunk size |
| `LISTEN_PORT` | `5000` | HTTP(S) port |
| `MAX_UPLOAD_KB` | `1000` | Max upload size per image |
| `MAX_UPLOAD_TOTAL_BYTES` | `52428800` | Max combined bytes per batch upload (50 MiB) |
| `MAX_UPLOAD_FILE_COUNT` | `50` | Max files per batch upload |
| `FUZZY_MIN_TOKEN_LENGTH` | `3` | Min length for filename/tag tokens in gallery fuzzy word match |
| `ENUMS_PATH` | `enums.yml` (repo root) | Path to category/license dictionary YAML |
| `CERT_PATH` | (unset) | TLS certificate; HTTPS only if set |
| `KEY_PATH` | (optional) | TLS private key |
| `LOG_LEVEL` | `INFO` | Log level for app and HTTP access logs |
| `LOG_SYSLOG` | `false` | Application logs (`app.*`) to syslog as `image-store` |
| `LOG_SYSLOG_ADDRESS` | `/dev/log` | Unix socket or `host:port` for remote syslog |

### `.env` (local)

```bash
cp .env.example .env
python run.py
```

Optional: `ENV_FILE=/path/to/file.env python run.py`. Shell exports override `.env` values. Do not commit `.env`.

### `.env` (Docker)

```bash
docker run --rm -p 5000:5000 \
  -v image-store-data:/data \
  --env-file .env \
  image-store
```

Map ports with `-p <host>:<container>` if you change `LISTEN_PORT`.

Details: [Features.md §10 Logging](Features.md#10-logging) for tee/syslog examples.

## Testing

Install dev dependencies and run pytest (see [AGENTS.md](AGENTS.md#testing)):

```bash
pip install -r requirements-dev.txt
export STORAGE_PATH=/tmp/image-store-test
pytest
```

Tests live in `tests/pytest/` and reference sections in [Features.md](Features.md). UI click targets use `data-testid` attributes for automation.

Playwright UI tests live in `tests/playwright/`. `conftest.py` starts Flask on `127.0.0.1:5000` with a fresh temp database (no manual `python run.py`). Fixture images for uploads are under `tests/data/images/set-01/`. Use a numeric prefix on filenames (e.g. `test_001-fresh_install.py`) so later pipeline tests run in order when you pass a directory to pytest. Install browsers once, then run headless:

```bash
playwright install chromium
pytest tests/pytest -q
pytest tests/playwright/ --browser chromium
```

To run only the fresh-install pipeline:

```bash
pytest tests/playwright/test_001-fresh_install.py --browser chromium
```

Quick smoke test without pytest:

```bash
STORAGE_PATH=/tmp/img-test .venv/bin/python -c "from app import create_app; create_app(); print('ok')"
```

## Integration

External apps use `GET /api/image` (URL or OTP), `GET /i/<uuid>/content` for direct downloads, and `/recall` with `redir` + OTP when needed. Sample clients under `sample-clients/`.

Full API, recall, OTP, and sample client steps: [Features.md §7–§11](Features.md#7-nickname-recall-recall).
