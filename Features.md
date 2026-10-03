# Features — Image Store (Phase 1)

Behavioral specification for the main application. Configuration and installation: [README.md](README.md). Agent conventions: [AGENTS.md](AGENTS.md).

## 1. Storage and database

- All state under `STORAGE_PATH`: SQLite DB (`store.db`), `thumbnails/{uuid}`, `fragments/public|user/{sha256}`.
- **Image** records: UUID, original name, upload time, MIME, size, sharing (`public` | `shared` | `private`), category (`general` | `adult` | `violent`), optional tags (JSON list), source, license.
- **Sharing** is set at upload and cannot be changed later.
- **Fragment** records: SHA-256 hex of padded chunk content, size in KB, image FK, index order.
- **Nickname** records: MD5 hex of description (PK), image FK, signed 64-bit hash from left 16 hex chars of MD5.
- Public fragments live under `fragments/public/`; shared/private under `fragments/user/`. Dedup and move rules per `app/services/fragments.py`.

## 2. Upload and processing

- Max size per image: `MAX_UPLOAD_KB`. Empty or non-image rejected.
- Public uploads require **source**; private clears source.
- Image split into fixed-size fragments (last chunk zero-padded); UUID assigned; default random nickname (dropped on MD5 conflict).
- Background thumbnail generation; after at least one thumbnail, localhost `POST /api/backup` may run.
- Batch upload: multiple files share one metadata form.

## 3. Gallery (landing `/`)

- Grid up to **6×10** thumbnails; default sort **latest upload** within category/sharing filters.
- **Latest** / **Random** view modes (random does not use search query).
- Single **search** box: fuzzy match on tags (weight 4), original name (2), category (1), sharing (1).
- **Category** and **sharing** filters in gear **Settings**; persisted in browser `sessionStorage` for the session.
- **Upload** control in site header only (separate from gallery controls).
- Pagination in header/footer of grid.
- Upload modal lists per-file failures and asks user to check server logs.

## 4. Image pages

- `/image/<id>` — full image, metadata, update tags and add nicknames (not sharing).
- `/i/<id>` — minimal image URL page (link home).
- `/i/<id>/content` — raw bytes for inline display in UI (not the external download API).

## 5. Nickname recall (`/recall`)

- Find nearest image by nickname text or 32-char MD5 hex.
- Link **Setup nicknames for recalling image** opens `/` in a new tab.
- **Done** behavior:
  - **callback** query param: POST `image_url` to callback URL (default callback = landing). If `callback` is set, **`redir` is ignored**.
  - **redir** + **idhash**: redirect to `redir?otp=<8 alphanumeric>`; requires `idhash` = base64(MD5(id bytes)).
- OTP: in-memory, **10s** TTL, unique among active OTPs; stores timestamp, image page URL, idhash.

## 6. Image download API (`/api/image`)

- Does **not** expose raw bytes via `GET` by UUID alone on a dedicated public ID endpoint.
- **By URL:** `GET ?url=<image page URL>` or `POST` JSON `{ "url": "..." }` (`image_url` alias).
- **By OTP (GET only):** `?otp=...&id=<base64 id bytes>` — validates idhash, returns bytes for stored image URL; **OTP always consumed** (success or failure).
- Errors: JSON `{ "error": "..." }` with non-2xx status.

## 7. Other HTTP API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/upload` | Multipart images + metadata |
| GET | `/api/images` | List/search (`page`, `category`, `sharing`, `q`, `tag`, `random=1`) |
| GET | `/api/images/<id>` | Metadata + nicknames |
| PATCH | `/api/images/<id>` | Tags, add nickname |
| POST | `/api/backup` | SQLite backup to `store.backup.db` |
| GET | `/api/nicknames/nearest?q=` | Nearest nickname match |

## 8. Logging

- Default: stderr (Werkzeug access at INFO + `app.*` application logs).
- `LOG_SYSLOG=true`: application logs to syslog as **`image-store`**; access logs remain on stderr unless redirected.
- Upload: received filename at INFO; ingest metadata at INFO (not nicknames); fragment names at DEBUG; errors at ERROR.

## 9. External integration

Image page URL form: `http://<host>/i/<uuid>`.

### Callback recall

```
/recall?callback=<url-encoded endpoint>
```

POST body: `image_url=<absolute /i/... URL>`.

### Redirect + OTP recall

```
/recall?redir=<receiver>&idhash=<base64(md5(id_bytes))>
```

Then `GET /api/image?otp=...&id=<base64(id_bytes)>`.

### Sample clients

| Path | Mechanism |
|------|-----------|
| `sample-clients/cli-downloader/` | CLI → `POST /api/image` |
| `sample-clients/app-callback/` | Recall `callback` (port 4999) |
| `sample-clients/app-redirect/` | Recall `redir` + OTP (port 4998) |

## 10. Deployment

- Optional HTTPS via `CERT_PATH` / `KEY_PATH`.
- Docker: volume on `/data`; optional `-v /dev/log:/dev/log` with `LOG_SYSLOG=true`.
