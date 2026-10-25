# Optional Windows tray dependencies

Sentinel Crier uses **pystray 0.19.5**, copyright Moses Palmér and contributors, under GNU LGPL version 3. The `pystray/` directory contains its source, source-build files and the GNU GPL/LGPL license texts, from [upstream v0.19.5](https://github.com/moses-palmer/pystray/tree/v0.19.5). The source files are copied from the exact installed distribution used to build this app. No application-specific changes are made to that library.

To build or replace the tray library, install Python and the source-build tools, then run `python -m pip install ./pystray` from this directory (the source uses `lib/pystray`). To rebuild Crier with a modified library, use the open application source and Windows build scripts at [Sentinel-Crier](https://github.com/Tetradim/Sentinel-Crier), install its documented build dependencies, install your modified pystray source with version `0.19.5`, then run `./desktop/build.ps1`. Crier's application code remains available under its own root license. The LGPL library retains its own terms.

**Pillow**, used to generate the tray image, and **six**, used by pystray, retain their licenses in `pillow/LICENSE` and `six/LICENSE`. Exact installed versions and the number of included tray source files are recorded in `bundle.json`. These libraries are separate dependencies; Crier's license does not replace theirs.
