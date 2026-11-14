"""Guard: no API key may ever be in a git-tracked file (keys belong in .env, which is git-ignored)."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = re.compile(rb"gsk_[A-Za-z0-9]{10,}|AIza[0-9A-Za-z_\-]{20,}")


def test_no_keys_in_tracked_files():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    offenders = [f for f in files if f and (ROOT / f).is_file() and KEY.search((ROOT / f).read_bytes())]
    assert offenders == [], f"API key found in tracked files: {offenders} (move it to .env)"


def test_env_is_ignored():
    r = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT)
    assert r.returncode == 0
