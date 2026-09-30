# Developed by ::> Gehan Fernando
"""Build the standalone Audio8D package for this computer's system, as a ZIP in bin.

    python packaging/build_release.py            (from the 8D folder)

It makes a private build environment, bundles FFmpeg 7 or newer, builds the
window and terminal programs with PyInstaller, zips the result as
bin/Audio8D-<version>-<system>-<processor>.zip, then unpacks that ZIP to a
folder with spaces in its name and checks it runs there with no Python on the
PATH. PyInstaller can't build for another system, so run this once on
Windows, once on Linux and once on macOS (or let the GitHub workflow do it)
to get all three ZIPs.

Only the standard library is used, so any Python 3.10 or newer can run it.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import venv
import zipfile
from pathlib import Path
from types import ModuleType

DESCRIPTION = "Build the standalone Audio8D package for this system as a ZIP in bin."
ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
BUILD = ROOT / "build"
# FFmpeg's afir filter needs 'irnorm' for the room sound; 6.1 lacks it, 7.0 works
MIN_FFMPEG = 7
# Where each system's FFmpeg comes from (Windows: the copy kept in the repository)
LINUX_FFMPEG = (
    "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
)
MAC_FFMPEG = {
    "arm64": (
        "https://www.osxexperts.net/ffmpeg9arm.zip",
        "https://www.osxexperts.net/ffprobe9arm.zip",
    ),
    "x86_64": (
        "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip",
        "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
    ),
}
# What travels with the programs in every package
EXTRAS = ("README.md", "THIRD-PARTY-NOTICES.md", "licenses")


class BuildError(RuntimeError):
    """A step failed; the message says which and what to do."""


def say(text: str) -> None:
    """One progress line."""
    print(f"==> {text}", flush=True)


def _locations() -> ModuleType:
    """Audio8D's own locations module (standard library only), loaded by path."""
    path = ROOT / "src" / "core" / "locations.py"
    spec = importlib.util.spec_from_file_location("audio8d_locations", path)
    if spec is None or spec.loader is None:
        raise BuildError(f"Cannot read {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def platform_tag() -> str:
    """'windows-x86_64', 'linux-x86_64', 'macos-arm64'…: the app's own names."""
    return str(_locations().platform_tag())


def project_version() -> str:
    """The version in pyproject.toml (read with a pattern: tomllib needs 3.11)."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    found = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not found:
        raise BuildError("pyproject.toml has no version line")
    return found.group(1)


def package_name(version: str, tag: str) -> str:
    """The ZIP's name, e.g. Audio8D-1.0.0-windows-x86_64.zip."""
    return f"Audio8D-{version}-{tag}.zip"


def exe(name: str) -> str:
    """A program's file name on this system."""
    return f"{name}.exe" if sys.platform == "win32" else name


def run(
    command: list[str],
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a command; unless check is False, a failure stops the build."""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, env=env, cwd=cwd
        )
    except OSError as exc:
        raise BuildError(f"Could not start {command[0]}: {exc}") from exc
    if check and result.returncode != 0:
        output = (result.stdout + result.stderr).strip()[-3000:]
        raise BuildError(f"{Path(command[0]).name} failed:\n{output}")
    return result


# ------------------------------------------------------------------ build environment


def build_python(tag: str) -> Path:
    """A private environment with PyInstaller and this version of Audio8D."""
    folder = BUILD / f"venv-{tag}"
    python = folder / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )
    if not python.exists():
        say(f"Creating the build environment in {folder}")
        venv.EnvBuilder(with_pip=True, clear=True).create(folder)
    say("Installing the build tools (needs the internet the first time)")
    run([str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--quiet",
            f"{ROOT}[gui]",
            "pyinstaller>=6.0",
        ]
    )
    # PyInstaller can't follow an editable install, so always copy in the current code
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-deps",
            "--force-reinstall",
            str(ROOT),
        ]
    )
    return python


# ------------------------------------------------------------------ FFmpeg


def ffmpeg_major(ffmpeg: Path) -> int:
    """FFmpeg's major version (0 when it can't be read, e.g. a git build)."""
    output = run([str(ffmpeg), "-hide_banner", "-version"]).stdout
    found = re.search(r"version\s+n?(\d+)\.", output)
    return int(found.group(1)) if found else 0


def download(url: str, target: Path) -> Path:
    """Fetch a file once; later builds reuse it."""
    if not target.exists():
        say(f"Downloading {url}")
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        try:
            with (
                urllib.request.urlopen(url, timeout=120) as response,
                partial.open("wb") as out,
            ):
                shutil.copyfileobj(response, out)
        except OSError as exc:
            partial.unlink(missing_ok=True)
            raise BuildError(f"Could not download {url}: {exc}") from exc
        partial.replace(target)
    return target


def linux_ffmpeg(folder: Path) -> None:
    """The static Linux build, checked against its published MD5 sum."""
    cache = BUILD / "downloads"
    archive = download(LINUX_FFMPEG, cache / "ffmpeg-release-amd64-static.tar.xz")
    try:
        with urllib.request.urlopen(LINUX_FFMPEG + ".md5", timeout=60) as response:
            expected = response.read().decode()
    except OSError as exc:
        raise BuildError(f"Could not download the FFmpeg MD5 sum: {exc}") from exc
    actual = hashlib.md5(archive.read_bytes()).hexdigest()
    if actual not in expected:
        archive.unlink()
        raise BuildError(
            "The FFmpeg download did not match its MD5 sum; run the build again"
        )
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if Path(member.name).name in ("ffmpeg", "ffprobe") and member.isfile():
                source = tar.extractfile(member)
                assert source is not None
                (folder / Path(member.name).name).write_bytes(source.read())


def mac_ffmpeg(folder: Path, machine: str) -> None:
    """Static macOS builds for this processor (arm64 or x86_64)."""
    if machine not in MAC_FFMPEG:
        raise BuildError(f"No macOS FFmpeg source is set up for {machine}")
    for tool, url in zip(("ffmpeg", "ffprobe"), MAC_FFMPEG[machine], strict=True):
        archive = download(url, BUILD / "downloads" / f"{tool}-macos-{machine}.zip")
        with zipfile.ZipFile(archive) as bundle:
            name = next((n for n in bundle.namelist() if Path(n).name == tool), None)
            if name is None:
                raise BuildError(f"{url} holds no {tool}")
            (folder / tool).write_bytes(bundle.read(name))


def get_ffmpeg(tag: str, chosen: Path | None) -> Path:
    """A folder with ffmpeg and ffprobe 7 or newer for this system."""
    if chosen is not None:
        folder = chosen
    elif tag.startswith("windows"):
        folder = ROOT / "vendor" / "ffmpeg" / tag
    else:
        folder = BUILD / "ffmpeg" / tag
        if not (folder / "ffmpeg").exists() or not (folder / "ffprobe").exists():
            folder.mkdir(parents=True, exist_ok=True)
            system, machine = tag.split("-", 1)
            if tag == "linux-x86_64":
                linux_ffmpeg(folder)
            elif system == "macos":
                mac_ffmpeg(folder, machine)
            else:
                raise BuildError(
                    f"No FFmpeg download is set up for {tag}: pass --ffmpeg-dir with "
                    "a folder holding ffmpeg and ffprobe 7 or newer"
                )
    for tool in ("ffmpeg", "ffprobe"):
        path = folder / exe(tool)
        if not path.is_file():
            hint = (
                " (run 'git lfs pull' in the repository)"
                if tag.startswith("windows")
                else ""
            )
            raise BuildError(f"Missing {path}{hint}")
        if path.stat().st_size < 1_000_000:
            raise BuildError(f"{path} is too small to be FFmpeg; run 'git lfs pull'")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    major = ffmpeg_major(folder / exe("ffmpeg"))
    if major < MIN_FFMPEG:
        raise BuildError(
            f"FFmpeg in {folder} is version {major}; "
            f"Audio8D needs {MIN_FFMPEG} or newer"
        )
    say(f"Using FFmpeg {major}.x from {folder}")
    return folder


# ------------------------------------------------------------------ packaging


def pyinstaller(python: Path, tag: str, ffmpeg: Path, version: str) -> Path:
    """Build the programs; returns the folder PyInstaller made."""
    dist, work = BUILD / f"dist-{tag}", BUILD / f"work-{tag}"
    say("Building the window and terminal programs with PyInstaller")
    env = {**os.environ, "AUDIO8D_FFMPEG_DIR": str(ffmpeg), "AUDIO8D_VERSION": version}
    run(
        [str(python), "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(dist), "--workpath", str(work),
         str(ROOT / "packaging" / "audio8d.spec")],
        env,
    )  # fmt: skip
    return dist


MAC_CLI = """#!/bin/sh
# The terminal program is inside Audio8D.app: next to this file, or in Applications
for app in "$(dirname "$0")/Audio8D.app" "/Applications/Audio8D.app"; do
    if [ -x "$app/Contents/MacOS/audio8d-cli" ]; then
        exec "$app/Contents/MacOS/audio8d-cli" "$@"
    fi
done
echo "Audio8D.app was not found next to this file or in Applications." >&2
exit 1
"""

HOW_TO_RUN = {
    "windows": "Double-click Audio8D.exe to open the window.\n"
    "audio8d-cli.exe is the command line: in a terminal, .\\audio8d-cli.exe --help\n",
    "linux": "Double-click Audio8D, or run ./Audio8D in a terminal, to open it.\n"
    "./audio8d-cli is the command line: ./audio8d-cli --help\n",
    "macos": "The first time, right-click Audio8D.app and choose Open (not signed).\n"
    "./audio8d-cli in this folder is the command line: ./audio8d-cli --help\n",
}


def stage(dist: Path, tag: str) -> Path:
    """The folder that goes into the ZIP: the programs plus the guide and licences."""
    system = tag.split("-", 1)[0]
    folder = BUILD / f"release-{tag}" / "Audio8D"
    if folder.parent.exists():
        shutil.rmtree(folder.parent)
    if system == "macos":
        folder.mkdir(parents=True)
        # symlinks=True keeps the app's inner links, which macOS needs
        shutil.copytree(dist / "Audio8D.app", folder / "Audio8D.app", symlinks=True)
        launcher = folder / "audio8d-cli"
        launcher.write_text(MAC_CLI, encoding="utf-8", newline="\n")
        launcher.chmod(0o755)
    else:
        shutil.copytree(dist / "Audio8D", folder, symlinks=True)
    for extra in EXTRAS:
        source = ROOT / extra
        target = folder / extra
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    (folder / "HOW TO RUN.txt").write_text(HOW_TO_RUN[system], encoding="utf-8")
    return folder


def walk(folder: Path) -> list[Path]:
    """Every folder, file and link under folder; links to folders are not followed."""
    found = [folder]
    for top, dirs, files in os.walk(folder, followlinks=False):
        found += [Path(top) / name for name in (*dirs, *files)]
    return sorted(found)


def write_zip(folder: Path, archive: Path) -> None:
    """Zip folder (as its own top folder), keeping executable bits and symlinks."""
    archive.parent.mkdir(parents=True, exist_ok=True)
    partial = archive.with_suffix(".zip.part")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        for path in walk(folder):
            name = path.relative_to(folder.parent).as_posix()
            info = (
                zipfile.ZipInfo.from_file(path, name)
                if not path.is_symlink()
                else zipfile.ZipInfo(name)
            )
            info.create_system = (
                3  # Unix, so unzip on macOS and Linux restores the modes
            )
            if path.is_symlink():
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                out.writestr(info, os.readlink(path))
            elif path.is_dir():
                info.external_attr = (stat.S_IFDIR | 0o755) << 16 | 0x10
                out.writestr(info, b"")
            else:
                mode = path.stat().st_mode
                # Windows has no executable bit: mark its programs executable anyway
                executable = mode & stat.S_IXUSR or path.suffix.lower() in (
                    ".exe",
                    ".dll",
                )
                info.external_attr = (
                    stat.S_IFREG | (0o755 if executable else 0o644)
                ) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with path.open("rb") as source, out.open(info, "w") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
    partial.replace(archive)


def extract(archive: Path, target: Path) -> Path:
    """Unzip like a user would, with modes and symlinks; returns the Audio8D folder."""
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            mode = info.external_attr >> 16
            path = target / info.filename
            if stat.S_ISLNK(mode):
                path.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(bundle.read(info).decode(), path)
            elif info.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, path.open("wb") as out:
                    shutil.copyfileobj(source, out, 1024 * 1024)
                if mode:
                    path.chmod(stat.S_IMODE(mode))
    return target / "Audio8D"


def cli_in(folder: Path, tag: str) -> Path:
    """The terminal program inside an unpacked package."""
    if tag.startswith("macos"):
        return folder / "Audio8D.app" / "Contents" / "MacOS" / "audio8d-cli"
    return folder / exe("audio8d-cli")


def user_environment(home: Path) -> dict[str, str]:
    """Settings like a fresh computer's: no Python, no build tools, own data folder."""
    system_path = (
        [os.environ.get("SystemRoot", r"C:\Windows") + r"\System32"]
        if sys.platform == "win32"
        else ["/usr/bin", "/bin"]
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("PYTHON", "VIRTUAL_ENV", "CONDA"))
    }
    env.update(
        PATH=os.pathsep.join(system_path), AUDIO8D_HOME=str(home), AUDIO8D_NO_WT="1"
    )
    return env


def check_contents(archive: Path) -> None:
    """The ZIP must not carry developer files."""
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    pattern = r"(^|/)(\.venv|venv|\.git|__pycache__|\.pytest_cache)(/|$)"
    unwanted = [name for name in names if re.search(pattern, name)]
    if unwanted:
        raise BuildError(f"The ZIP holds developer files: {unwanted[:5]}")


def check_package(archive: Path, tag: str) -> None:
    """Unpack the ZIP to a path with spaces and run it with no Python on the PATH."""
    say(f"Checking {archive.name} as a user would run it")
    check_contents(archive)
    with tempfile.TemporaryDirectory(prefix="audio8d check ") as temp:
        outside = Path(temp)  # runs from outside the package and the repository
        folder = extract(archive, outside / "unpacked here")
        cli = cli_in(folder, tag)
        if not cli.is_file():
            raise BuildError(f"The ZIP has no terminal program at {cli}")
        env = user_environment(outside / "home")
        version = run([str(cli), "--version"], env, outside).stdout.strip()
        checked = run([str(cli), "--check"], env, outside, check=False)
        if (
            checked.returncode != 0
            or "Everything required is ready" not in checked.stdout
        ):
            raise BuildError(
                "The unpacked package failed its --check:\n"
                + (checked.stdout + checked.stderr)[-2000:]
            )
        # A real conversion with the bundled FFmpeg: a short generated tone
        tone = outside / "test tone.wav"
        bundled = folder / "Audio8D.app" if tag.startswith("macos") else folder
        ffmpeg = next((p for p in bundled.rglob(exe("ffmpeg")) if p.is_file()), None)
        if ffmpeg is None:
            raise BuildError("The ZIP has no bundled ffmpeg")
        tone_input = ["-f", "lavfi", "-i", "sine=frequency=440:duration=6"]
        run([str(ffmpeg), "-hide_banner", "-loglevel", "error", *tone_input,
             "-ac", "2", str(tone)], env)  # fmt: skip
        run([str(cli), str(tone), "--output-dir", str(outside / "out")], env, outside)
        made = sorted((outside / "out").glob("*.mp3"))
        if not made:
            raise BuildError("The unpacked package ran but made no song")
    say(f"Checked: {version}; --check ready; converted a test tone to {made[0].name}")


def clean_bin(keep: Path) -> None:
    """bin holds only release ZIPs: remove older programs left by earlier builds."""
    for leftover in (
        "Audio8D.exe",
        "audio8d-cli.exe",
        "_internal",
        "Audio8D",
        "audio8d-cli",
    ):
        path = BIN / leftover
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    say(f"Package ready: {keep.relative_to(ROOT)}")


def main(argv: list[str] | None = None) -> int:
    """Build, zip and check this system's package."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument(
        "--ffmpeg-dir", type=Path, help="use ffmpeg and ffprobe from this folder"
    )
    parser.add_argument(
        "--skip-check", action="store_true", help="don't test the finished ZIP"
    )
    args = parser.parse_args(argv)
    tag, version = platform_tag(), project_version()
    try:
        say(f"Building Audio8D {version} for {tag}")
        ffmpeg = get_ffmpeg(tag, args.ffmpeg_dir)
        python = build_python(tag)
        dist = pyinstaller(python, tag, ffmpeg, version)
        folder = stage(dist, tag)
        archive = BIN / package_name(version, tag)
        say(f"Writing {archive.relative_to(ROOT)}")
        write_zip(folder, archive)
        if not args.skip_check:
            check_package(archive, tag)
        clean_bin(archive)
    except BuildError as exc:
        print(f"\nBuild failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
