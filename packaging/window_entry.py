# Developed by ::> Gehan Fernando
"""Audio8D.exe: opens the window; songs dropped on the exe arrive as arguments."""

import sys

# audio8d is the installed name of src, which only exists inside the build
# pylint: disable-next=import-error,no-name-in-module
from audio8d.cli import main  # pyright: ignore[reportMissingImports]

if __name__ == "__main__":
    sys.exit(main(["--gui", *sys.argv[1:]]))
