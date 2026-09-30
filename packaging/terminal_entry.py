# Developed by ::> Gehan Fernando
"""audio8d-cli.exe: the terminal app, exactly like `audio8d` in Python."""

import sys

# audio8d is the installed name of src, which only exists inside the build
# pylint: disable-next=import-error,no-name-in-module
from audio8d.cli import main  # pyright: ignore[reportMissingImports]

if __name__ == "__main__":
    sys.exit(main())
