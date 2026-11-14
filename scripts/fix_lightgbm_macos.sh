#!/usr/bin/env bash
# LightGBM's macOS wheel needs libomp (normally `brew install libomp`).
# If Homebrew isn't available, reuse the libomp that scikit-learn's wheel bundles.
# Usage: bash scripts/fix_lightgbm_macos.sh   (run after pip install, inside the venv)
set -euo pipefail
PY="${PYTHON:-.venv/bin/python}"
if "$PY" -c "import lightgbm" 2>/dev/null; then echo "lightgbm already imports fine"; exit 0; fi
SITE=$("$PY" -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
SRC="$SITE/sklearn/.dylibs/libomp.dylib"
DST_DIR="$SITE/lightgbm/lib"
[ -f "$SRC" ] || { echo "No bundled libomp found; run: brew install libomp"; exit 1; }
cp "$SRC" "$DST_DIR/libomp.dylib"
install_name_tool -add_rpath @loader_path "$DST_DIR/lib_lightgbm.dylib" 2>/dev/null || true
codesign -f -s - "$DST_DIR/libomp.dylib" "$DST_DIR/lib_lightgbm.dylib"
"$PY" -c "import lightgbm; print('lightgbm', lightgbm.__version__, 'OK')"
