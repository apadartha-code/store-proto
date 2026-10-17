# Features — Image Store (v2)

Behavioral specification for the main application. Configuration and installation: [README.md](README.md). Agent conventions: [AGENTS.md](AGENTS.md).

Phase 1 behavior is preserved unless noted below; v2 adds the data dictionary, multi-category images, license rules, 24-bit nicknames, gallery sharing default, batch upload limits, and recall multi-select.

---

## 1. Data dictionary (`enums.yml`)

Enumerated **category** and **license** values are defined in YAML at the repo root (override path with `ENUMS_PATH`). Loaded at startup by `app/services/dictionary.py`.

### Categories

Map keyed by display name (e.g. `General`). Each entry has:

| Field | Meaning |
|-------|---------|
| `id` | Stable integer stored in the database (`image_categories.category_id`) |
| `help` | Human-readable applicability text (default `""`) |

String keys and ids are one-to-one. Seed data:

| Key | ID | Help (summary) |
|-----|----|----------------|
| General | 0 | Unrestricted access for all age groups |
| Adult | 1 | Not for children; eroticism, strong violence, grotesque/macabre, etc. |
| Violent | 2 | Content that triggers fear |
| Grotesque | 3 | Strongly displeasing or revolting |

### Licenses

Map keyed by display name. Each entry has `id`, `help`, and optional `sharing` restriction (`Public`, `Shared`, or `Private`, case-insensitive in YAML). If `sharing` is omitted, the license may be used with any sharing type.

| Key | ID | Sharing restriction | Help (summary) |
|-----|----|---------------------|----------------|
| Private | 0 | Private | Private images |
| Unknown | 1 | Shared | License unknown |
| Platform Contributed | 2 | Shared | Platform-owned material under custom license |
| Creative Commons (CC) | 3 | Public | Broad CC family |
| Public Domain | 4 | Public | Expired, waived, or never copyrighted works |

Upload and PATCH validate that the chosen license is allowed for the image’s **sharing** (set at upload only).

When upload metadata omits `license`, the app picks the lowest-id license valid for that sharing (e.g. public → Creative Commons (CC), shared → Unknown, private → Private).

---

## 2. Storage and database

- All state under `STORAGE_PATH`: SQLite DB (`store.db`), `thumbnails/{uuid}`, `fragments/public|user/{sha256}`.
- **No migration tooling** — schema is created on init for new databases; existing Phase 1 DBs are not upgraded automatically.

### Image records

UUID, original name, upload time, MIME, **image_size** (bytes), **content_checksum** (SHA-256 hex of raw file bytes), **sharing** (`public` | `shared` | `private`), **license_id** (dictionary), optional tags (JSON list), optional **source** (required for public at upload). **`(content_checksum, image_size)` is unique** — duplicate bytes are rejected when sharing is unchanged or tightened (`private` → `shared` → `public` is increasing relaxation). A duplicate with **more relaxed** sharing updates **sharing** and **license** only; other metadata and `original_name` stay as-is; fragments move to `public/` when relaxing to **public**.

- **Sharing** is set at upload and **cannot** be changed later in UI or API.
- **Categories**: one-to-many via `image_categories (image_id, category_id)`. Every category id must exist in `enums.yml`. Gallery category filter matches images that include that category.

### Fragment records

SHA-256 hex of padded chunk content, size in KB, image FK, index order. Public fragments under `fragments/public/`; shared/private under `fragments/user/`. Dedup and move rules: `app/services/fragments.py`.

### Nickname records

`nicknames (hash, image_id)` — composite primary key on **24-bit hash** (integer) and image id. **No MD5** nickname table. Multiple images may share the same hash (collisions allowed).

### Backup

`POST /api/backup` writes `store.backup.db` under a write lock (see §11).

---

## 3. Upload and processing

### Per-file limits

- Max size per image: `MAX_UPLOAD_KB`. Empty or non-image rejected.
- Public uploads require **source**; private uploads clear source.

### Batch limits (v2)

- `MAX_UPLOAD_TOTAL_BYTES` (default **50 MiB**): combined raw bytes of all files in one request.
- `MAX_UPLOAD_FILE_COUNT` (default **50**): number of files in one request.
- If either limit is exceeded, the entire upload is rejected (HTTP 400).

### Metadata

- **Categories**: one or more dictionary keys (checkboxes in UI; form field `categories`). At least one required.
- **License**: must be valid for selected sharing; upload form filters license options by sharing.
- **Tags**: optional comma-separated or list.
- **Sharing**: `public` | `shared` | `private`.

### Pipeline

- Image split into fixed-size fragments (`FRAGMENT_SIZE_KB`, last chunk zero-padded); UUID assigned; **content_checksum** stored and deduplicated with **image_size**; duplicate relax relocates existing fragment files to `public/` when needed (`relocate_fragments_for_sharing_change`); if a fragment file is missing, ingest falls back to `split_into_fragments` for the new sharing.
- On upload: **random 24-bit nickname hash** inserted (collisions allowed).
- Background thumbnail generation; after at least one thumbnail, localhost `POST /api/backup` may run.
- Batch upload: multiple files share one metadata form (`POST /api/upload`, multipart field `files`).
- Upload modal lists per-file failures and prompts checking server logs.

---

## 4. Gallery (landing `/`)

- Grid up to **6×10** thumbnails (`PAGE_ROWS` × `PAGE_COLS`); default sort **latest upload** within category/sharing filters.
- **Latest** / **Random** view modes (`random=1`) when **not** searching. **Random** and **search** are mutually exclusive: with a non-empty `q`, Latest/Random controls are hidden and results are ranked by **fuzzy relevance score** only (higher score first; ties by `upload_time` ascending). Random browsing does not apply a search query.
- Single **search** box: fuzzy match with weights — **tags (4)**, original name **(2)**, **categories (1)** (all assigned category names), **sharing (1)**. Per-field token matching ignores tokens shorter than **`FUZZY_MIN_TOKEN_LENGTH`** (default **3**) so single-letter filename segments (e.g. Flickr `_o`) do not match unrelated query terms; whole-field substring match (`query` contained in the field text) is unchanged. A **×** control at the right of the field clears the query and reloads the gallery without `q` (category/sharing/random filters unchanged); hidden when the field is empty.
- **Category** filter (General, Adult, Violent, Grotesque, All) and **sharing** filter in gear **Settings**; persisted in browser `sessionStorage` for the session.
- **Sharing** default filter: **Public and Shared** (`public_and_shared`) — includes both `public` and `shared` images, excludes `private`.
- **Upload** control in site header only (not in gallery toolbar).
- Pagination in header/footer of grid.
- **Bulk selection** (latest, search, and random grids): checkbox on each thumbnail; toolbar on the pager row (right-aligned) shows selected count (with **Clear**), **Select All** (current page), and **Bulk edit** (disabled when nothing selected). Selection is stored in `sessionStorage` and persists across pagination until the gallery context changes (`q`, `category`, `sharing`, `random`) or a bulk edit submit succeeds.
- **Bulk edit** (`/bulk-edit`): opens with the current `sessionStorage` selection (gallery query params are not required on this URL). **Cancel** / **Done** return to the gallery using the stored search/filter context when available. Left pane lists selected thumbnails (checkboxes control which rows are included in submit; unchecking does not remove the thumbnail). **Select All** / **Clear** above the scroll area; **Clear** unchecks all and disables submit. Right pane: category checkboxes (when at least one is checked, categories **replace** all assignments on selected images) and comma-separated tags (**merged** into existing tags, case-insensitive dedup). **Cancel** returns to the gallery; after a successful submit it reads **Done** (same link). Success overlay auto-fades; failure overlay requires dismiss. `POST /api/images/bulk-edit` with `image_ids` and optional `categories` / `tags`.

---

## 5. Image pages

| Route | Purpose |
|-------|---------|
| `/image/<id>` | Full image, metadata, edit tags, **categories** (checkboxes with help tooltips), **license** (select + inline help), set **nickname** (not sharing). **Save** uses the same acknowledgement overlays as bulk edit: success auto-fades then the page reloads; failure requires **Dismiss**. |
| `/i/<id>` | Minimal image URL page (link home) |
| `/i/<id>/content` | Raw bytes for inline display in UI (not the external download API) |
| `/thumb/<id>` | Thumbnail JPEG for gallery/recall |

---

## 6. Nicknames

- **On upload**: random 24-bit hash stored; shown as **6 lowercase hex digits** where displayed.
- **User-assigned nickname**: replaces prior nickname rows for that image; hash = first 24 bits of SHA-256 of UTF-8 input (same 6-hex display). Collisions across images are allowed.
- **Recall / API lookup**: user may enter nickname text or a **6-character hex hash**. Lookup uses the 24-bit hash (SHA-256 prefix for text). If no image has that exact hash, the **nearest** stored hash is used: the largest hash ≤ target, or the maximum hash in the database if target is below all stored values (same ordering rule as Phase 1 MD5 nicknames). All images sharing the matched or nearest hash are returned.

---

## 7. Nickname recall (`/recall`)

- **Find**: POST `/recall/find` with nickname → lists all images with matching hash.
- Link **Setup nicknames for recalling image** opens `/` in a **new tab**.
- If **multiple** images match, each row has a checkbox; **Done** stays **disabled** until at least one image is selected.

### Browse (no integration query params)

Find nicknames, select matches, and press **Done** to return to the gallery (`/`). **Full** links open bytes at `/i/<uuid>/content`.

### Done — redirect + OTP mode

Query: `redir=<receiver>` and `idhash=<base64(MD5(id_bytes))>` (`idhash` required).

After selection, redirect to `redir?otp=<8 alphanumeric>`. OTP is created for the **first** selected image URL. Receiver uses `GET /api/image` with OTP (see §8).

### OTP store

In-memory, **10s** TTL, unique among active OTPs; stores timestamp, image page URL, idhash.

---

## 8. Image download API (`/api/image`)

Does **not** expose raw bytes via a public `GET` by UUID alone on a dedicated ID endpoint.

| Mode | Request |
|------|---------|
| By URL | `GET ?url=<image page URL>` (`image_url` query alias) |
| By OTP (GET only) | `?otp=...&id=<base64 id bytes>` — validates idhash, returns bytes for stored image URL; **OTP always consumed** (success or failure) |

Errors: JSON `{ "error": "..." }` with non-2xx status.

Image page URL form: `http://<host>/i/<uuid>`.

---

## 9. Other HTTP API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/upload` | Multipart `files` + metadata (`sharing`, `categories`, `license`, `source`, `tags`) |
| GET | `/api/images` | List/search (`page`, `category`, `sharing`, `q`, `tag`); `random=1` returns a random page when `q` is omitted (`q` wins if both are sent) |
| GET | `/api/images/<id>` | Metadata, `categories`, license key, `nickname_hashes` (6-hex), `image_url` |
| PATCH | `/api/images/<id>` | `tags`, `categories`, `license`, `nickname` (not sharing) |
| POST | `/api/backup` | SQLite backup to `store.backup.db` |
| GET | `/api/nicknames/nearest?q=` | Nickname or 6-hex lookup with **nearest-hash** fallback; JSON `{ "items": [...], "count" }` or 404 |

Default list `sharing` when omitted: `public_and_shared`.

---

## 10. Logging

- Default: stderr (Werkzeug access at INFO + `app.*` application logs).
- `LOG_SYSLOG=true`: application logs to syslog as **`image-store`**; access logs remain on stderr unless redirected.
- Upload: received filename at INFO; ingest metadata at INFO (not nickname secrets); fragment names at DEBUG; errors at ERROR.

---

## 11. External integration

### Direct image bytes (curl / wget)

When the image store is reachable on your LAN (or you trust the host), raw bytes are available at:

```
GET /i/<uuid>/content
```

Example: `curl -o photo.jpg 'http://<host>/i/<uuid>/content'` or the same URL with `wget -O photo.jpg`.

This route is intended for simple scripts and tools; it is separate from `/api/image` (OTP / image-page URL validation).

### Redirect + OTP recall

```
/recall?redir=<receiver>&idhash=<base64(md5(id_bytes))>
```

Then `GET /api/image?otp=...&id=<base64(id_bytes)>`.

### Sample clients

| Path | Mechanism |
|------|-----------|
| `sample-clients/batch-uploader/` | CLI batch `POST /api/upload` (glob patterns, limits from `.env`) |
| `sample-clients/app-redirect/` | Recall `redir` + OTP (port 4998) |

**Batch uploader** (`upload_batch.py`): stdlib-only. Inputs: `-F`/`--paths-list` (one image path per line, or `-` for stdin) and/or `-g`/`--glob` (directory scan; globs converted to regex and walked with `os.walk`). With both, `-F` paths are processed first and excluded from `-g` scan. No folder scan without `-g`. `-I`/`--ignore-file` lists paths or directories to skip (directories prune scan). Producer/consumer threads enqueue eligible files (size/mime/ignore filtered) and upload in batches (consumer starts after `10 × MAX_UPLOAD_FILE_COUNT` queued items or when scanning finishes). Logs `LIST`, `ENQUEUE`, `SCAN_DIR_COMPLETE`, `OK`/`FAIL` for restart via `-F`/`-I`. Requires `--sharing` and `--license` (valid keys in `enums.yml`); `--source` when public. Limits from `./.env`, environment, then `--env-file`. Flags: `--dry-run`, `--brief`, `--host` (default `127.0.0.1:5000`), `--upload-timeout` (seconds per batch HTTP call, default `30`). Ctrl+C stops the producer scan immediately and finishes the consumer’s in-flight upload, then exits with restart hints. Manual checks: [sample-clients/batch-uploader/MANUAL_TEST_CHECKLIST.md](sample-clients/batch-uploader/MANUAL_TEST_CHECKLIST.md). Run with `-h` for full help.

---

## 12. Deployment

- Optional HTTPS via `CERT_PATH` / `KEY_PATH`.
- Docker: volume on `/data`; `enums.yml` baked into image; optional `-v /dev/log:/dev/log` with `LOG_SYSLOG=true`.
