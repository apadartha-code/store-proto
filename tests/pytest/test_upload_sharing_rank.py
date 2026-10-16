"""Features.md §3 Upload — sharing relaxation rank helper."""

from __future__ import annotations

import pytest

from app.services.errors import UploadValidationError
from app.services.upload import sharing_relaxation_rank


def test_sharing_relaxation_rank_order():
    assert sharing_relaxation_rank("private") < sharing_relaxation_rank("shared")
    assert sharing_relaxation_rank("shared") < sharing_relaxation_rank("public")


def test_sharing_relaxation_rank_invalid():
    with pytest.raises(UploadValidationError):
        sharing_relaxation_rank("invalid")
