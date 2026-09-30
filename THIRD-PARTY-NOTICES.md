<!-- Developed by ::> Gehan Fernando -->
# Third-party software in Audio8D

Audio8D is developed by Gehan Fernando. The standalone app (`Audio8D` and `audio8d-cli`; `Audio8D.exe` and `audio8d-cli.exe` on Windows) ships with the following third-party software. Each keeps its own licence; the full texts are in the `licenses` folder next to this file.

Paths below are relative to the `Audio8D` folder you unzipped. On macOS the same files are inside `Audio8D.app`.

| Component | Version | Licence | Where it is | Licence text |
|---|---|---|---|---|
| **FFmpeg** and **FFprobe** (see [FFmpeg source code](#ffmpeg-source-code) for the build used on each system) | Windows: 9.0.2; Linux: 7.0.2 | GNU General Public License v3 (built with `--enable-gpl --enable-version3`) | `_internal\ffmpeg.exe`, `_internal\ffprobe.exe` (`_internal/ffmpeg`, `_internal/ffprobe` on Linux) | `licenses/FFmpeg-GPL-3.0.txt` |
| **Python** (with Tcl/Tk and the libraries listed in its licence) | Windows: 3.12.10; Linux: 3.10.12 | Python Software Foundation License | `_internal` | `licenses/Python-LICENSE.txt` |
| **CustomTkinter** | 6.0.0 | MIT | inside the programs and `_internal\customtkinter` | `licenses/CustomTkinter-LICENSE.txt` |
| **darkdetect** (used by CustomTkinter) | 0.8.0 | BSD 3-Clause | inside the programs | `licenses/darkdetect-LICENSE.txt` |
| **packaging** (used by CustomTkinter) | 26.3 | Apache 2.0 or BSD 2-Clause | inside the programs | `licenses/packaging-LICENSE.txt`, `licenses/packaging-LICENSE.APACHE.txt` |
| **Pillow** | 12.3.0 | MIT-CMU (HPND) | `_internal\PIL` | `licenses/Pillow-LICENSE.txt` |
| **PyInstaller** bootloader | 6.22.3 | GPL 2.0 with the bootloader exception (it places no conditions on the programs it starts) | the two programs | `licenses/PyInstaller-COPYING.txt` |

The Python libraries and PyInstaller are installed at exactly these versions by the build, from `packaging/requirements-build.txt` in the source repository.

## FFmpeg source code

FFmpeg is free software under the GNU GPL v3. Audio8D runs the unmodified `ffmpeg` and `ffprobe` as separate programs; it does not change or link to them. FFmpeg's source code for every release is at <https://ffmpeg.org/download.html>. Each package's build, with the source of every library inside it:

- **Windows (x86_64):** the "release essentials" build by gyan.dev, version 9.0.2: <https://www.gyan.dev/ffmpeg/builds/>. Its full configuration is shown by `_internal\ffmpeg.exe -version`.
- **Linux (x86_64):** the static "release" build by John Van Sickle, version 7.0.2: <https://johnvansickle.com/ffmpeg/>, with its source at <https://johnvansickle.com/ffmpeg/release-source/>. Its full configuration is shown by `_internal/ffmpeg -version`.
- **macOS:** no macOS package has been built yet. When one is, it uses the static builds from <https://www.osxexperts.net/> (Apple silicon) or <https://evermeet.cx/ffmpeg/> (Intel), and this list will name the version.

Under the GPL you may also ask whoever gave you this copy of Audio8D for the corresponding source code.
