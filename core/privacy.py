"""Masking helpers: no phone number or full VPA is ever shown."""
from __future__ import annotations

import re

PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
VPA_RE = re.compile(r"[^\s@,;:()\[\]\"']+@[a-zA-Z]\w+")


def mask_vpa(vpa: str | None) -> str:
    """'9849012345@ybl' -> '98******45@ybl'; 'ramesh.k@okaxis' -> 'ra******.k@okaxis'."""
    if not vpa:
        return ""
    if "@" not in vpa:
        return "******"
    local, handle = vpa.split("@", 1)
    if len(local) <= 4:
        masked = local[:1] + "******"
    else:
        masked = local[:2] + "******" + local[-2:]
    return f"{masked}@{handle}"


def is_masked_vpa(token: str) -> bool:
    return "******" in token


def find_unmasked_vpas(text: str) -> list[str]:
    return [m.group(0) for m in VPA_RE.finditer(text) if not is_masked_vpa(m.group(0))]


def find_phone_numbers(text: str) -> list[str]:
    return [m.group(0) for m in PHONE_RE.finditer(text)]
