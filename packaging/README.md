# Windows portable build

Use a clean Python 3.11 x64 environment. This deliberately excludes the developer's
global packages, CUDA toolkit and any `data/` or browser-profile directories.

```powershell
python -m venv .packaging-venv
.packaging-venv\Scripts\python -m pip install -r packaging/requirements-build.txt
npm ci
npm run build
gh release download latest -R BtbN/FFmpeg-Builds -p ffmpeg-n8.1-latest-win64-lgpl-shared-8.1.zip -p checksums.sha256 -D packaging/downloads
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD/packaging/browser-cache"
.packaging-venv\Scripts\python -m playwright install chromium --no-shell
```

Find the downloaded `chromium-*` directory containing `chrome-win64/chrome.exe`,
then pass that directory to the builder:

```powershell
.packaging-venv\Scripts\python scripts/build_portable.py --browser-dir packaging/browser-cache/chromium-REVISION
```

`packaging/icon.ico` and version metadata are repository assets. The builder
verifies the FFmpeg publisher checksum, runs PyInstaller, adds the complete
Chromium runtime and codec DLLs, preserves license notices and produces:

`release/StrokeScape-0.1.0-Windows-x64.zip`

Before publishing, run `scripts/verify_portable.py` against the **extracted ZIP**.
The test uses a fresh data folder, a separate port and the package's own browser
and FFmpeg; it generates a work and exports a real MP4. Publish matching FFmpeg
source/build recipes with the release as described in THIRD_PARTY_NOTICES.md.

The application is an unsigned early release. Code signing and an optional
installer can be added later without changing the portable data format.
