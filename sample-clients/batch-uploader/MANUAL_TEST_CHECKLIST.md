# Batch uploader — manual test checklist

Manual checks for `upload_batch.py` (Features.md §11). Mark each row **Pass** / **Fail** / **Skip** and note the log file path.

**Setup (common)**

- Image Store running (`python run.py`, `STORAGE_PATH` set).
- Repo `.env` (or `--env-file`) defines `MAX_UPLOAD_KB`, `MAX_UPLOAD_TOTAL_BYTES`, `MAX_UPLOAD_FILE_COUNT`.
- Sample images available (e.g. a directory tree with many PNG/JPEG files).
- Run from `sample-clients/batch-uploader/` or pass full paths; use `--log-file` with a known path when debugging interrupt cases.

```bash
# Example (adjust host, license, paths):
python upload_batch.py -g '/path/to/photos/**/*.jpg' \
  --sharing private --license 'Private' \
  --host 127.0.0.1:5000 --log-file /tmp/batch-manual.log
```

---

## Interrupt (Ctrl+C)

| ID | Case | Steps | Expected | Result |
|----|------|--------|----------|--------|
| INT-1 | **Message on first Ctrl+C** | Start a real upload (`-g` or `-F`, not `--dry-run`) with enough files for at least one batch. Press **Ctrl+C once** while uploads are in progress. | stderr shows: `Interrupt received; finishing current upload if any…` | |
| INT-2 | **In-flight batch completes** | During INT-1, note which batch is uploading (stderr `Uploading batch …` or log `BATCH size=…`). After Ctrl+C, watch server/logs until that HTTP request finishes. | Current `POST /api/upload` completes; log has `OK`/`FAIL` for every file in that batch; process does **not** exit mid-request. | |
| INT-3 | **No new batches after interrupt** | After INT-2, confirm no further `BATCH` / `Uploading batch` lines for files that were not yet in the in-flight batch. | Consumer stops scheduling new batches once interrupt is set (queue may still drain only for the active batch). | |
| INT-4 | **Exit code 130** | After the run ends following Ctrl+C, check shell exit status (`echo $?` if run interactively, or script wrapper). | Exit code **130** (standard for SIGINT). | |
| INT-5 | **Summary and log path on stderr/stdout** | Read terminal output at end of interrupted run. | Lines include `done: uploaded=… failed=…`, `log file: <path>`, and restart text mentioning `-F`/`--paths-list` and `-I`/`--ignore-file` built from the log. | |
| INT-6 | **Log records interruption** | Open the operation log from INT-5. | Final line includes `END … interrupted=True` (or `interrupted=True` in the `END` record). | |
| INT-7 | **Restart hint content** | From the same log, identify lines usable for resume. | `ENQUEUE` / `LIST` lines support rebuilding a paths list for `-F`; `SCAN_DIR_COMPLETE` (and `SKIP ignore`) lines support rebuilding `-I` after a scan was interrupted. | |
| INT-8 | **Ctrl+C between batches** | Use a small tree and limits so batches are small; press Ctrl+C **after** one batch finishes and **before** the next starts. | No new batch starts; exit 130; log reflects uploads completed before interrupt. | |
| INT-9 | **Ctrl+C during producer scan (`-g`)** | Start a large `-g` walk (slow disk or deep tree). Press Ctrl+C while scanning/enqueue activity is ongoing. | Interrupt flag is set (INT-1 message); **producer stops walking** promptly (no full-tree completion); consumer per INT-3–INT-6; process can exit without waiting for the entire scan. | |
| INT-10 | **Dry-run + Ctrl+C** | `upload_batch.py … --dry-run` with `-g` or `-F`, Ctrl+C during run. | Graceful shutdown with exit **130**, log path and restart hint printed; no HTTP upload calls to the server. | |
| INT-11 | **Second Ctrl+C** | During INT-2 (upload in flight), press Ctrl+C **again**. | Process still waits for in-flight upload to finish (no corrupt partial exit); document any duplicate interrupt messages. | |

**Notes**

- Automated pytest does **not** cover these yet; see `tests/pytest/test_batch_uploader.py` (pipeline tests pass an unset `interrupt` event only).
- On platforms without `pthread_sigmask`, in-thread SIGINT blocking during upload may differ; Linux is the reference environment.

---

## Other areas (TODO)

_Add checklist sections here as needed (paths list, glob scan, ignore file, dry-run, limits, etc.)._
