"""Aksharantar check logic, tested OFFLINE on a tiny hand-made fixture (never the real download)."""
from experiments import aksharantar_eval as ak

ROWS = [
    {"native word": "लक्ष्मी", "english word": "lakshmi", "source": "fixture"},
    {"native word": "लक्ष्मी", "english word": "laxmi", "source": "fixture"},
    {"native word": "सुनीता", "english word": "suneeta", "source": "fixture"},
    {"native word": "सुनीता", "english word": "sunita", "source": "fixture"},
    {"native word": "रमेश", "english word": "ramesh", "source": "fixture"},
    {"native word": "रमन", "english word": "raman", "source": "fixture"},
    {"native word": "वाला", "english word": "wala", "source": "fixture"},        # descriptor: excluded
    {"native word": "x", "english word": "ab", "source": "fixture"},             # too short: excluded
]


def test_pairs_and_scores():
    same, diff = ak.build_pairs(ROWS, n=10)
    assert sorted(same) == [("lakshmi", "laxmi"), ("suneeta", "sunita")]
    assert diff == [("raman", "ramesh")] or diff == [("ramesh", "raman")]
    s = ak.score_pairs(same)
    assert s["n"] == 2 and s["identical_after_folding"] == 1.0 and s["auto_match"] == 1.0
    d = ak.score_pairs(diff)
    assert d["auto_match"] == 0.0


def test_excludes_descriptors_and_short_words():
    assert not ak.usable("wala") and not ak.usable("ab") and ak.usable("lakshmi")
