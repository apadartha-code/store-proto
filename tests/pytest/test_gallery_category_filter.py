"""Features.md §4 — gallery category filter matches enums.yml."""

from __future__ import annotations


def test_landing_category_filter_lists_all_enum_categories(client, app):
    from app.services.dictionary import get_dictionary

    dd = get_dictionary()
    res = client.get("/")
    assert res.status_code == 200
    assert b'data-testid="settings-category"' in res.data
    for key in dd.category_keys():
        assert f'data-testid="settings-category-option-{key}"'.encode() in res.data
        assert f'value="{key.lower()}"'.encode() in res.data
    assert b'data-testid="settings-category-option-All"' in res.data
    assert b'value="all"' in res.data
