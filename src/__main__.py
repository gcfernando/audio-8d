# Developed by ::> Gehan Fernando
"""Starts Audio8D, whether it is installed or run straight from the src folder."""

import sys

# Running from src skips pip's version gate, so stop politely on old Pythons here
if sys.version_info < (3, 10):  # noqa: UP036
    found = sys.version.split()[0]
    sys.exit(f"Audio8D needs Python 3.10 or newer, but this is Python {found}.")

if __package__:
    # Normal route: the installed `audio8d` command or `python -m audio8d`
    from .cli import main
else:
    # Not installed (`python src`, `python __main__.py`): register src as audio8d
    import importlib.util
    from pathlib import Path

    here = Path(__file__).resolve().parent

    # Take src off the import path so folders like `ffmpeg` can't shadow other packages
    sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != here]

    spec = importlib.util.spec_from_file_location(
        "audio8d", here / "__init__.py", submodule_search_locations=[str(here)]
    )
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    sys.modules["audio8d"] = package
    spec.loader.exec_module(package)

    # Imported by name because linters can't see the package registered just above
    main = importlib.import_module("audio8d.cli").main

if __name__ == "__main__":
    raise SystemExit(main())
