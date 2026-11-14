"""Shopkeeper-facing strings from app/i18n.json. Unreviewed languages fall back to English per key."""
from __future__ import annotations

import json
from functools import lru_cache

import config

LANGS = {"en": "English", "hi": "हिन्दी", "te": "తెలుగు"}


@lru_cache(maxsize=1)
def _strings() -> dict:
    return json.loads(config.I18N_PATH.read_text(encoding="utf-8"))


def t(key: str, lang: str = "en", **kw) -> str:
    s = _strings()
    template = s.get(lang, {}).get(key) or s["en"].get(key)
    if template is None:
        raise KeyError(f"missing i18n key {key!r}")
    return template.format(**kw)


def coverage(lang: str) -> tuple[int, int]:
    s = _strings()
    return len([k for k in s["en"] if k in s.get(lang, {})]), len(s["en"])
