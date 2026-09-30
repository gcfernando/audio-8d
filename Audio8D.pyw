# Developed by ::> Gehan Fernando
r"""Double-click me to open the Audio8D window (.pyw files run with no console).

Songs or folders dropped onto this file in File Explorer open with the window.
The same window: python src\__main__.py --gui   (or audio8d-gui once installed).
"""

import runpy
import sys
from pathlib import Path

# Everything after the file name (songs dropped onto this file) goes to the window
sys.argv = [sys.argv[0], "--gui", *sys.argv[1:]]
runpy.run_path(
    str(Path(__file__).resolve().parent / "src" / "__main__.py"), run_name="__main__"
)
