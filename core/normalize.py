"""Name cleaning for matching UPI names to khata names.

lowercase -> strip honorifics/descriptors (kept as `hints`) -> split initials -> transliteration folds.
Names are used ONLY for identity matching; they never reach the trust model.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

HONORIFICS = {
    "ji", "bhai", "bhaiya", "bhaiyya", "anna", "amma", "garu", "sir", "madam", "didi", "akka", "dada", "babu",
    "saab", "sahab", "saheb", "mr", "mrs", "ms", "smt", "shri", "sri", "shree", "dr", "aunty", "aunti", "uncle",
    "bhabhi", "behen", "mataji", "chacha", "mama", "thambi", "appa", "ayya", "bhau", "tai", "ben",
}
DESCRIPTORS = {
    "dudh", "doodh", "wala", "wale", "wali", "vala", "vale", "vali", "kirana", "auto", "driver", "teacher",
    "tailor", "sabzi", "sabji", "milk", "milkman", "dhobi", "chai", "medical", "maid", "watchman", "security",
    "shop", "store", "colony", "flat", "no", "house", "opp", "near", "new", "old", "office", "school", "mandir",
    "masjid", "church", "temple", "gate", "building", "block", "road", "plumber", "electrician", "painter",
    "mechanic", "carpenter", "barber", "cook", "nurse", "contractor", "petrol", "pump",
}
# transliteration-friendly folds (small, documented list): x<->ksh, v<->w, ee<->i, oo<->u, plus aa->a, th->t
_FOLDS = [("ksh", "x"), ("w", "v"), ("ee", "i"), ("oo", "u"), ("aa", "a"), ("th", "t"), ("ph", "f")]


@dataclass
class NormName:
    raw: str
    tokens: list[str] = field(default_factory=list)     # folded full-name tokens
    initials: list[str] = field(default_factory=list)   # single letters ("k" from "RAMESH K" / "K.")
    hints: list[str] = field(default_factory=list)      # stripped honorifics/descriptors ("dudh", "wala")

    @property
    def key(self) -> str:
        return " ".join(self.tokens)

    @property
    def is_blank(self) -> bool:
        return not self.tokens


def fold(token: str) -> str:
    t = token
    for a, b in _FOLDS:
        t = t.replace(a, b)
    # collapse doubled letters (Lakshmi/Laxmi/Lakshmii)
    t = re.sub(r"(.)\1+", r"\1", t)
    return t


def normalize(name: str | None) -> NormName:
    raw = name or ""
    s = unicodedata.normalize("NFKC", raw).lower()
    s = re.sub(r"[0-9]+", " ", s)                 # flat numbers etc.
    s = s.replace(".", " . ")
    s = re.sub(r"[^a-zऀ-෿ .]+", " ", s)  # keep Latin + Indic letters
    parts = [p for p in s.split() if p]
    out = NormName(raw=raw)
    for p in parts:
        if p == ".":
            continue
        if p in HONORIFICS or p in DESCRIPTORS:
            out.hints.append(p)
        elif len(p) == 1:
            out.initials.append(p)
        else:
            out.tokens.append(fold(p))
    return out
