# Developed by ::> Gehan Fernando
"""Small helpers the window tests share: waiting, adding songs, reading text."""

import shutil
import time
from pathlib import Path


def pump(window, until, seconds: float = 90.0) -> None:
    """Let the window run until a condition is true (or give up)."""
    end = time.time() + seconds
    while not until() and time.time() < end:
        window.update()
        time.sleep(0.02)
    window.update()


def read(app, paths) -> None:
    """Add songs and wait until their details have been read."""
    app.add_paths(list(paths))
    # Folders are looked through on a helper thread first
    pump(app, lambda: not app.scans_waiting, 60)
    pump(app, lambda: all(t.state != "reading" for t in app.library.tracks), 60)


def tagged(source: Path, target: Path, **tags: str) -> Path:
    """A copy of a song with the given tags (genre, artist…)."""
    import subprocess  # pylint: disable=import-outside-toplevel

    from src.ffmpeg import FFmpegToolchain  # pylint: disable=import-outside-toplevel

    ffmpeg = FFmpegToolchain.discover().ffmpeg
    arguments = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                 "-i", str(source), "-c", "copy"]  # fmt: skip
    for key, value in tags.items():
        arguments += ["-metadata", f"{key}={value}"]
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([*arguments, str(target)], check=True)
    return target


def entries(widget) -> list:
    """Every text box inside a widget, however deep."""
    found = []
    for child in widget.winfo_children():
        if child.__class__.__name__ == "CTkEntry":
            found.append(child)
        found += entries(child)
    return found


def texts(widget) -> list[str]:
    """Every label's text inside a widget, however deep."""
    found = []
    for child in widget.winfo_children():
        try:
            found.append(str(child.cget("text")))
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        found += texts(child)
    return found


def copies(app, source: Path, folder: Path, *names: str) -> list[Path]:
    """Copies of one song under other names, added to the window and read."""
    made = [folder / name for name in names]
    for target in made:
        shutil.copy(source, target)
    read(app, made)
    return made


def customize(app, songs, style: str | None = None, **sound) -> None:
    """Customize songs through the real dialog, as someone would, then Apply."""
    app.open_customize(list(songs))
    dialog = app.customize
    if style is not None:
        dialog._style_picked(style)  # pylint: disable=protected-access
    if sound:
        dialog.tune(**sound)
    dialog.apply()
    app.update()
