<!-- Developed by ::> Gehan Fernando -->
# Third-party software in Audio8D

Audio8D is developed by Gehan Fernando. The standalone app (`Audio8D.exe`, `audio8d-cli.exe`) ships with the following third-party software. Each keeps its own licence; the full texts are in the `licenses` folder next to this file.

| Component | Version | Licence | Where it is | Licence text |
|---|---|---|---|---|
| **FFmpeg** and **FFprobe** (the "essentials" build by gyan.dev) | 9.0.2 | GNU General Public License v3 (built with `--enable-gpl --enable-version3`) | `bin\ffmpeg.exe`, `bin\ffprobe.exe` | `licenses/FFmpeg-GPL-3.0.txt` |
| **Python** (with Tcl/Tk and the libraries listed in its licence) | 3.12.10 | Python Software Foundation License | `bin\_internal` | `licenses/Python-LICENSE.txt` |
| **CustomTkinter** | 6.0.0 | MIT | inside the programs and `bin\_internal\customtkinter` | `licenses/CustomTkinter-LICENSE.txt` |
| **darkdetect** (used by CustomTkinter) | 0.8.0 | BSD 3-Clause | inside the programs | `licenses/darkdetect-LICENSE.txt` |
| **packaging** (used by CustomTkinter) | 26.3 | Apache 2.0 or BSD 2-Clause | inside the programs | `licenses/packaging-LICENSE.txt`, `licenses/packaging-LICENSE.APACHE.txt` |
| **Pillow** | 12.3.0 | MIT-CMU (HPND) | `bin\_internal\PIL` | `licenses/Pillow-LICENSE.txt` |
| **PyInstaller** bootloader | 6.22.3 | GPL 2.0 with the bootloader exception (it places no conditions on the programs it starts) | the two `.exe` files | `licenses/PyInstaller-COPYING.txt` |

## FFmpeg source code

FFmpeg is free software under the GNU GPL v3. Audio8D runs the unmodified `ffmpeg.exe` and `ffprobe.exe` as separate programs; it does not change or link to them.

- FFmpeg's source code, for every release: <https://ffmpeg.org/download.html> (version 9.0.2).
- The exact build used here, with the source of every library inside it: <https://www.gyan.dev/ffmpeg/builds/> ("release essentials", 9.0.2). The build's full configuration is shown by `bin\ffmpeg.exe -version`.

Under the GPL you may also ask whoever gave you this copy of Audio8D for the corresponding source code.
