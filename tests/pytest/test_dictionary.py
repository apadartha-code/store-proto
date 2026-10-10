"""Features.md §1 — data dictionary (enums.yml)."""

from __future__ import annotations


def test_category_and_license_maps(app):
    from app.services.dictionary import get_dictionary

    dd = get_dictionary()
    general = dd.category_by_key("General")
    assert general is not None
    assert general.id == 0
    assert "unrestricted" in general.help.lower()

    lic = dd.license_by_key("Public Domain")
    assert lic is not None
    assert lic.sharing == "public"


def test_license_sharing_validation(app):
    from app.services.dictionary import get_dictionary

    dd = get_dictionary()
    assert dd.validate_license_for_sharing("Private", "private")
    assert not dd.validate_license_for_sharing("Private", "public")


def test_default_license_for_sharing(app):
    from app.services.dictionary import get_dictionary

    dd = get_dictionary()
    assert dd.default_license_key_for_sharing("public") == "Creative Commons (CC)"
    assert dd.default_license_key_for_sharing("shared") == "Unknown"
    assert dd.default_license_key_for_sharing("private") == "Private"
