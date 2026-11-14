"""Download the real public datasets used by the validation layer (plan 13b). Never imported by the app.

Raw files go to experiments/raw/ (git-ignored, never redistributed). Every file gets a manifest entry:
source URL, access date, licence seen, SHA-256, size.

    python experiments/download.py
"""
from __future__ import annotations

import hashlib
import json
import ssl
import sys
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "experiments" / "raw"
MANIFEST = ROOT / "reports" / "dataset_manifest.json"

DATASETS = {
    "uci_online_retail_ii": {
        "url": "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip",
        "page": "https://archive.ics.uci.edu/dataset/502/online+retail+ii",
        "licence": "CC BY 4.0 (verified on the UCI dataset page, 2026-11-14)",
        "citation": "Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5CG6D",
    },
    "uci_default_credit_card_taiwan": {
        "url": "https://archive.ics.uci.edu/static/public/350/default+of+credit+card+clients.zip",
        "page": "https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients",
        "licence": "CC BY 4.0 (verified on the UCI dataset page, 2026-11-14)",
        "citation": "Yeh, I. (2009). Default of Credit Card Clients [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C55S3H",
    },
}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text())
    except Exception:
        return {}


def save_manifest(m: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m, indent=1))


def main(names: list[str] | None = None) -> None:
    m = load_manifest()
    for name, d in DATASETS.items():
        if names and name not in names:
            continue
        out_dir = RAW / name
        out_dir.mkdir(parents=True, exist_ok=True)
        zpath = out_dir / Path(d["url"]).name.replace("+", "_")
        if not zpath.exists():
            print(f"downloading {name} ...")
            if not d["url"].startswith("https://archive.ics.uci.edu/"):
                raise ValueError("only the hard-coded https UCI URLs are allowed")
            req = urllib.request.Request(d["url"], headers={"User-Agent": "pakkakhata-validation/1.0"})
            import certifi   # python.org builds on macOS ship without CA certs; verify with certifi's bundle
            ctx = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(req, timeout=300, context=ctx) as r:  # nosec B310
                zpath.write_bytes(r.read())
        with zipfile.ZipFile(zpath) as z:
            members = [i for i in z.infolist() if not i.is_dir() and ".." not in i.filename and not i.filename.startswith("/")]
            for i in members:   # safe extraction: plain names only, into this dataset's own folder
                target = out_dir / Path(i.filename).name
                if not target.exists():
                    target.write_bytes(z.read(i))
        files = [p for p in out_dir.iterdir() if p.is_file()]
        m.setdefault(name, {}).update({
            "source_url": d["url"], "page": d["page"], "access_date": date.today().isoformat(), "licence_seen": d["licence"], "citation": d["citation"],
            "files": {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size} for p in sorted(files)},
        })
        print(f"{name}: {[p.name for p in files]}")
    save_manifest(m)


if __name__ == "__main__":
    main(sys.argv[1:] or None)
