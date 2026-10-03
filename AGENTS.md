# AGENTS.md — Image Store (Phase 1)

Guidance for automated coding agents working in this repository.

## Project summary

LAN-hostable **image gallery** with SQLite persistence, **SHA-256 fragment** file storage, **nickname recall**, and external download via **`/api/image`**. Main app: **Flask** + **SQLite** + **Pillow**. Phase 1 only—extend in small, spec-aligned diffs.

User-facing documentation: [README.md](README.md). Feature behavior: [Features.md](Features.md).

## Repository layout

| Path | Purpose |
|------|---------|
| `app/` | Main Flask application |
| `app/config.py` | Env-based configuration (`Config`) |
| `app/db.py` | SQLite schema, sessions, write lock for backup |
| `app/routes/web.py` | HTML UI (landing, detail, recall, image pages) |
| `app/routes/api.py` | JSON/multipart API |
| `app/services/` | Domain logic (upload, fragments, thumbnails, nicknames, query, otp, backup, image_download) |
| `app/templates/`, `app/static/` | Jinja templates and CSS |
| `run.py` | Entrypoint; loads `.env` via `python-dotenv` when installed |
| `sample-clients/` | Standalone demos (not imported by main app) |
| `Dockerfile` | Production image; `STORAGE_PATH=/data` volume |

Do not treat `.venv/`, `data/`, or `__pycache__` as product code.

## General
- Maintain Features.md to describe the capabilities of the application
- Always make sure to update Features.md when updating or adding a feature.
- Use README.md for information on basic description, integration, installation and testing.
- For actual features and details of behavior, point to Features.md

## Testing
- Always include data-testid on clickable elements.
- Use pytest for unit tests.
- Ensure that no unit test is modified after generation without explicit review and approval. If a test breaks, suggest the reason and the change required.
- Place unit tests in tests/pytest
- Always write a unit test for any new helper function.
- Ensure that test cases refer to proper feature section in Features.md in comments.
- Run pytest after every feature change and bugfix.

## Run and verify

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export STORAGE_PATH=./data
python run.py
```

Smoke test (no server):

```bash
STORAGE_PATH=/tmp/img-test .venv/bin/python -c "from app import create_app; create_app(); print('ok')"
```

Docker: `docker build -t image-store .` then run with `-v` on `/data`.

## Architecture constraints (do not break without explicit ask)

1. **Sharing** is set at upload time and must not become editable later in UI/API.
2. **Raw image bytes** are not served by UUID on a public GET API. Downloads use **`GET|POST /api/image`** with an **image page URL** (`/i/<uuid>`) or **`otp` + `id`** (GET only).
3. **Fragments**: padded chunks, SHA-256 filenames; `public` vs `user` folders per spec in `app/services/fragments.py`.
4. **Nicknames**: MD5 hex primary key; nearest-match hash logic in `app/services/nickname.py`.
5. **Recall**: `callback` (POST `image_url`) **or** `redir` + `idhash` (redirect with OTP). If both query params are present, **callback wins**. OTP store: in-memory, 10s TTL, `app/services/otp.py`.
6. **Backup**: `POST /api/backup` uses SQLite backup under write lock; thumbnail worker may trigger localhost backup after thumbnails.

## Configuration

All runtime settings come from **environment variables** (`app/config.py`). Optional `.env` at repo root is loaded in `run.py`. See README **Configuration** and `.env.example`.

## Logging

- App loggers live under the `app.*` namespace.
- Werkzeug access logs stay at INFO on stderr.
- Optional syslog: `LOG_SYSLOG=true`, ident `image-store` (application logs only).
- Upload/ingest errors use `logger.error`; fragment SHA-256 names at DEBUG.

## Code conventions

- **Python 3.8+** in dev; Docker uses 3.12. Use `from __future__ import annotations` in modules that use `dict[str, …]` or `X | Y` types.
- Prefer **minimal diffs**; match existing Flask blueprint + service layer split.
- New HTTP features: `web.py` for HTML, `api.py` for JSON/binary; put logic in `app/services/`.
- SQLite: use `db_session()` / `write_lock()` from `app/db.py`; enable foreign keys (already set).
- No commits unless the user requests them.

## UI notes

- Landing: single fuzzy search box; category/sharing in gear **Settings** (sessionStorage); upload button in **header** only.
- Recall: link to `/` opens in new tab for nickname setup.

## Sample clients

Independent Flask/CLI apps under `sample-clients/`—change them without coupling to `app` imports:

| Folder | Role |
|--------|------|
| `cli-downloader/` | Stdlib CLI → `POST /api/image` |
| `app-callback/` | Recall with `callback` (port 4999) |
| `app-redirect/` | Recall with `redir` + OTP (port 4998) |

## Common tasks

| Task | Where to look |
|------|----------------|
| Upload pipeline | `app/services/upload.py`, `POST /api/upload` |
| Gallery search | `app/services/query.py` (weighted fuzzy `q`) |
| Image download API | `app/services/image_download.py`, `app/routes/api.py` |
| Recall + OTP | `app/routes/web.py`, `app/services/otp.py` |
| Thumbnails / backup side effects | `app/services/thumbnail.py` |

## Out of scope unless requested

- Authentication, multi-user ACLs, cloud object storage replacing fragment files
- Changing Phase 1 schema semantics (sharing immutability, fragment layout rules)
