# Image Store (Phase 1)

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

Details: [Features.md §8 Logging](Features.md#8-logging) for tee/syslog examples.

## Testing

Install dev dependencies and run pytest (see [AGENTS.md](AGENTS.md#testing)):

```bash
pip install -r requirements-dev.txt
export STORAGE_PATH=/tmp/image-store-test
pytest
```

Tests live in `tests/pytest/` and reference sections in [Features.md](Features.md). UI click targets use `data-testid` attributes for automation.

Quick smoke test without pytest:

```bash
STORAGE_PATH=/tmp/img-test .venv/bin/python -c "from app import create_app; create_app(); print('ok')"
```

## Integration

External apps download images via `/api/image` and optional `/recall` flows (callback or redirect + OTP). Sample clients under `sample-clients/`.

Full API, recall, OTP, and sample client steps: [Features.md §5–§9](Features.md#5-nickname-recall-recall).
