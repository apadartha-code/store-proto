from __future__ import annotations

from __future__ import annotations

import base64
import hashlib
import secrets
import string
import threading
import time
from dataclasses import dataclass
from typing import Optional

OTP_TTL_SECONDS = 10
OTP_LENGTH = 8
_ALPHANUM = string.ascii_letters + string.digits

_lock = threading.Lock()
_store: dict[str, "OtpRecord"] = {}


@dataclass
class OtpRecord:
    created_at: float
    image_url: str
    idhash: str


def _purge_expired(now: float | None = None) -> None:
    now = now or time.time()
    expired = [k for k, v in _store.items() if now - v.created_at > OTP_TTL_SECONDS]
    for key in expired:
        del _store[key]


def idhash_for_id_bytes(id_bytes: bytes) -> str:
    return base64.b64encode(hashlib.md5(id_bytes).digest()).decode("ascii")


def id_matches_idhash(id_b64: str, expected_idhash: str) -> bool:
    try:
        id_bytes = base64.b64decode(id_b64, validate=True)
    except Exception:
        return False
    computed = idhash_for_id_bytes(id_bytes)
    return computed == expected_idhash


def create_otp(image_url: str, idhash: str) -> str:
    with _lock:
        now = time.time()
        _purge_expired(now)
        for _ in range(200):
            otp = "".join(secrets.choice(_ALPHANUM) for _ in range(OTP_LENGTH))
            if otp in _store:
                continue
            _store[otp] = OtpRecord(created_at=now, image_url=image_url, idhash=idhash)
            return otp
    raise RuntimeError("Unable to allocate a unique OTP")


def pop_otp(otp: str) -> Optional[OtpRecord]:
    """Remove OTP if present; return record only if still within TTL."""
    with _lock:
        _purge_expired()
        record = _store.pop(otp, None)
    if record is None:
        return None
    if time.time() - record.created_at > OTP_TTL_SECONDS:
        return None
    return record


def resolve_image_url_from_otp(otp: str, id_b64: str) -> Optional[str]:
    """Validate OTP + id, return image URL. OTP is always consumed if it exists."""
    record = pop_otp(otp)
    if record is None:
        return None
    if not id_matches_idhash(id_b64, record.idhash):
        return None
    return record.image_url
