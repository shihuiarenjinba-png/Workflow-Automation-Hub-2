from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

SUPPORTED_LOCALES = ("ja", "en")


def resource_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")) / "resources"
    return Path(__file__).resolve().parent.parent / "resources"


@lru_cache(maxsize=4)
def _load(locale: str) -> dict[str, str]:
    locale = locale if locale in SUPPORTED_LOCALES else "ja"
    path = resource_root() / "i18n" / f"{locale}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def tr(locale: str, key: str, **kwargs: Any) -> str:
    data = _load(locale)
    fallback = _load("en")
    text = data.get(key, fallback.get(key, key))
    try:
        return text.format(**kwargs)
    except (KeyError, ValueError):
        return text
