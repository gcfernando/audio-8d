# Developed by ::> Gehan Fernando

# Window and terminal programs sharing one bundled folder; built by build_release.py

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "src" / "assets" / "audio8d.ico")
# CustomTkinter's themes and fonts, and Audio8D's icon
DATAS = collect_data_files("customtkinter") + [(ICON, "audio8d/assets")]
# macOS Finder litter that CustomTkinter ships; its PyInstaller hook adds it too
JUNK = {".DS_Store"}
# Big optional extras that Audio8D never needs in the standalone build
EXCLUDES = ["demucs", "torch", "torchaudio", "numpy", "pytest", "IPython"]
# build_release.py names the folder holding this system's ffmpeg and ffprobe
FFMPEG_DIR = os.environ.get("AUDIO8D_FFMPEG_DIR", "")
EXE_SUFFIX = ".exe" if sys.platform == "win32" else ""
FFMPEG = [
    (str(Path(FFMPEG_DIR) / f"{tool}{EXE_SUFFIX}"), ".")
    for tool in ("ffmpeg", "ffprobe")
    if FFMPEG_DIR
]
# Version details are a Windows feature of the .exe file
VERSION = str(ROOT / "packaging" / "version.txt") if sys.platform == "win32" else None


def analysis(script, binaries=()):
    return Analysis(
        [str(ROOT / "packaging" / script)],
        pathex=[str(ROOT)],
        binaries=list(binaries),
        datas=DATAS,
        hiddenimports=["audio8d.gui_app"],
        excludes=EXCLUDES,
        noarchive=False,
    )


# FFmpeg is added once; both programs share the same bundled files
window = analysis("window_entry.py", FFMPEG)
terminal = analysis("terminal_entry.py")


def program(built, name, console):
    return EXE(
        PYZ(built.pure),
        built.scripts,
        [],
        exclude_binaries=True,
        name=name,
        icon=ICON,
        console=console,
        upx=False,
        version=VERSION,
    )


def without_junk(toc):
    # Filtered here, after every hook has run, so no route can sneak the files back in
    return [entry for entry in toc if Path(entry[0]).name not in JUNK]


collected = COLLECT(
    program(window, "Audio8D", console=False),
    window.binaries,
    without_junk(window.datas),
    program(terminal, "audio8d-cli", console=True),
    terminal.binaries,
    without_junk(terminal.datas),
    upx=False,
    name="Audio8D",
)

if sys.platform == "darwin":
    # A normal Mac app: Audio8D.app, with the terminal program inside Contents/MacOS
    app = BUNDLE(
        collected,
        name="Audio8D.app",
        icon=ICON,
        bundle_identifier="net.gehanfernando.audio8d",
        info_plist={
            "CFBundleShortVersionString": os.environ.get("AUDIO8D_VERSION", "0"),
            "NSHighResolutionCapable": True,
        },
    )
