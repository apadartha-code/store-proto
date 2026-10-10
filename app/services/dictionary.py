from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

from app.config import Config

_SHARING_VALUES = frozenset({"public", "shared", "private"})


@dataclass(frozen=True)
class CategoryDef:
    key: str
    id: int
    help: str


@dataclass(frozen=True)
class LicenseDef:
    key: str
    id: int
    help: str
    sharing: Optional[str]


class DataDictionary:
    def __init__(self, raw: dict[str, Any]) -> None:
        self._categories_by_key: dict[str, CategoryDef] = {}
        self._categories_by_id: dict[int, CategoryDef] = {}
        for key, item in (raw.get("category") or {}).items():
            cat = CategoryDef(key=key, id=int(item["id"]), help=str(item.get("help") or ""))
            self._categories_by_key[key] = cat
            self._categories_by_id[cat.id] = cat

        self._licenses_by_key: dict[str, LicenseDef] = {}
        self._licenses_by_id: dict[int, LicenseDef] = {}
        for key, item in (raw.get("license") or {}).items():
            sharing_raw = item.get("sharing")
            sharing = str(sharing_raw).lower() if sharing_raw else None
            if sharing and sharing not in _SHARING_VALUES:
                raise ValueError(f"Invalid sharing on license {key}: {sharing}")
            lic = LicenseDef(
                key=key,
                id=int(item["id"]),
                help=str(item.get("help") or ""),
                sharing=sharing,
            )
            self._licenses_by_key[key] = lic
            self._licenses_by_id[lic.id] = lic

        self._validate_bijections()

    def _validate_bijections(self) -> None:
        if len(self._categories_by_id) != len(self._categories_by_key):
            raise ValueError("Duplicate category id in enums.yml")
        if len(self._licenses_by_id) != len(self._licenses_by_key):
            raise ValueError("Duplicate license id in enums.yml")

    def category_keys(self) -> list[str]:
        return sorted(self._categories_by_key.keys(), key=lambda k: self._categories_by_key[k].id)

    def license_keys(self) -> list[str]:
        return sorted(self._licenses_by_key.keys(), key=lambda k: self._licenses_by_key[k].id)

    def category_by_key(self, key: str) -> Optional[CategoryDef]:
        return self._categories_by_key.get(key)

    def category_by_id(self, category_id: int) -> Optional[CategoryDef]:
        return self._categories_by_id.get(category_id)

    def license_by_key(self, key: str) -> Optional[LicenseDef]:
        return self._licenses_by_key.get(key)

    def license_by_id(self, license_id: int) -> Optional[LicenseDef]:
        return self._licenses_by_id.get(license_id)

    def licenses_for_sharing(self, sharing: str) -> list[LicenseDef]:
        s = sharing.lower()
        result = []
        for lic in self._licenses_by_key.values():
            if lic.sharing is None or lic.sharing == s:
                result.append(lic)
        return sorted(result, key=lambda x: x.id)

    def validate_license_for_sharing(self, license_key: str, sharing: str) -> bool:
        lic = self.license_by_key(license_key)
        if not lic:
            return False
        if lic.sharing is None:
            return True
        return lic.sharing == sharing.lower()

    def default_license_key_for_sharing(self, sharing: str) -> str:
        """First valid license for sharing (lowest id)."""
        choices = self.licenses_for_sharing(sharing.lower())
        if not choices:
            raise ValueError(f"No license defined for sharing {sharing}")
        return choices[0].key


_dictionary: Optional[DataDictionary] = None


def load_dictionary(path: Optional[Path] = None) -> DataDictionary:
    global _dictionary
    if _dictionary is not None and path is None:
        return _dictionary
    p = path or Config.ENUMS_PATH
    with open(p, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    dd = DataDictionary(raw)
    if path is None:
        _dictionary = dd
    return dd


def get_dictionary() -> DataDictionary:
    return load_dictionary()


def reset_dictionary_cache() -> None:
    global _dictionary
    _dictionary = None
