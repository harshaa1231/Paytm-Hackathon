"""Optional Indian-data check: does our name normalisation cope with real Latin spelling variation of Hindi and
Telugu words?

Data: AI4Bharat Aksharantar (Hindi + Telugu train splits), JSON lines {native word, english word, source}.
Licence per the dataset card: manually collected data CC-BY, mined/existing sources CC0; cite arXiv:2205.03018.
Raw files stay in experiments/raw/ (git-ignored, not redistributed).

1. Variant recall: a native word that appears with 2+ different Latin spellings gives a "same word" pair
   (e.g. two spellings of the same Telugu word). Would our matcher still connect them?
2. False-match proxy: two DIFFERENT native words whose Latin forms start with the same 3 letters. If these were
   names, an auto-match would be a false match.
Limitation: these are general words, not personal names, and the data has no name labels.

    python experiments/download.py aksharantar_hin aksharantar_tel && python experiments/aksharantar_eval.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from core.matcher import name_score  # noqa: E402
from core.normalize import DESCRIPTORS, HONORIFICS, normalize  # noqa: E402

RAW = ROOT / "experiments" / "raw"
SEED = 42
N_SAMPLE = 3000


def usable(word: str) -> bool:
    w = word.strip().lower()
    return w.isascii() and w.isalpha() and len(w) >= 4 and w not in HONORIFICS and w not in DESCRIPTORS


def build_pairs(rows: Iterable[dict], n: int = N_SAMPLE, seed: int = SEED) -> tuple[list, list]:
    by_native: dict[str, set] = defaultdict(set)
    for r in rows:
        e = (r.get("english word") or "").strip().lower()
        if usable(e):
            by_native[r["native word"]].add(e)
    rng = np.random.default_rng(seed)
    variants = [sorted(v)[:2] for v in by_native.values() if len(v) >= 2]
    rng.shuffle(variants)
    same = [tuple(v) for v in variants[:n]]
    # different native words that look alike in Latin (same first 3 letters, different spelling)
    by_prefix: dict[str, list] = defaultdict(list)
    for native, v in by_native.items():
        w = sorted(v)[0]
        by_prefix[w[:3]].append((native, w))
    diff = []
    for group in by_prefix.values():
        if len(group) >= 2:
            idx = rng.choice(len(group), size=2, replace=False)
            (n1, a), (n2, b) = group[idx[0]], group[idx[1]]
            if n1 != n2 and a != b:
                diff.append((a, b))
    rng.shuffle(diff)
    return same, diff[:n]


def score_pairs(pairs: list[tuple[str, str]]) -> dict:
    thr, lo = config.MATCH_CONFIDENT_SCORE, config.MATCH_MIN_SCORE
    scores = np.array([name_score(normalize(a), normalize(b))[0] for a, b in pairs]) if pairs else np.array([])
    folded_equal = sum(normalize(a).key == normalize(b).key for a, b in pairs)
    n = len(pairs)
    return {"n": n,
            "identical_after_folding": round(folded_equal / n, 4) if n else None,
            "auto_match": round(float((scores >= thr).mean()), 4) if n else None,
            "ambiguous_to_llm_or_shopkeeper": round(float(((scores >= lo) & (scores < thr)).mean()), 4) if n else None,
            "no_match": round(float((scores < lo).mean()), 4) if n else None}


def evaluate(rows: Iterable[dict], n: int = N_SAMPLE) -> dict:
    same, diff = build_pairs(rows, n)
    return {"same_word_variants": score_pairs(same), "different_lookalike_words": score_pairs(diff),
            "examples_same": [list(p) for p in same[:8]], "examples_diff": [list(p) for p in diff[:8]]}


def read_jsonl(path: Path) -> Iterable[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def run() -> dict:
    out = {"dataset": "AI4Bharat Aksharantar (Hindi, Telugu train splits)",
           "licence": "Dataset card: manually collected data CC-BY; mined and existing sources CC0. Cite arXiv:2205.03018.",
           "auto_match_threshold": f"name score >= {config.MATCH_CONFIDENT_SCORE}",
           "limitation": "General words, not personal names; no name labels. Checks spelling-variation handling only.",
           "languages": {}}
    for lang in ("hin", "tel"):
        path = RAW / f"aksharantar_{lang}" / f"{lang}_train.json"
        out["languages"][lang] = evaluate(read_jsonl(path))
    (ROOT / "reports" / "aksharantar_metrics.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


if __name__ == "__main__":
    r = run()
    for lang, v in r["languages"].items():
        print(lang, "same-word variants:", v["same_word_variants"])
        print(lang, "different look-alike words:", v["different_lookalike_words"])
        print("   e.g.", v["examples_same"][:4], "|", v["examples_diff"][:4])
