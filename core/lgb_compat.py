"""Import shim: give a clear message if LightGBM can't find libomp on macOS."""
try:
    import lightgbm  # noqa: F401
except OSError as e:  # pragma: no cover
    raise ImportError(
        "LightGBM could not load libomp. On macOS run `brew install libomp`, or without Homebrew: "
        "`bash scripts/fix_lightgbm_macos.sh`") from e
