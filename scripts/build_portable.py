"""Build a Windows x64 portable folder and ZIP without copying user data.

Run in a clean environment prepared with packaging/requirements-build.txt.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.0'
FFMPEG_ARCHIVE = 'ffmpeg-n8.1-latest-win64-lgpl-shared-8.1.zip'


def checked_run(command, **kwargs):
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    return subprocess.run(command, check=True, **flags, **kwargs)


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def prepare_ffmpeg(downloads, runtime):
    archive = downloads / FFMPEG_ARCHIVE
    sums = downloads / 'checksums.sha256'
    if not archive.is_file() or not sums.is_file():
        raise SystemExit('Download FFmpeg and checksums first; see packaging/README.md')
    expected = None
    for line in sums.read_text(encoding='utf-8').splitlines():
        if line.split() and line.split()[-1].lstrip('*') == FFMPEG_ARCHIVE:
            expected = line.split()[0]
            break
    actual = checksum(archive)
    if not expected or actual.lower() != expected.lower():
        raise RuntimeError('FFmpeg SHA256 does not match the publisher checksum')
    binary_dir = runtime / 'bin'
    notices = runtime / 'ffmpeg-notices'
    binary_dir.mkdir(parents=True, exist_ok=True)
    notices.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            relative = Path(item.filename)
            if relative.name == 'ffplay.exe':
                continue
            if '/bin/' in item.filename and not item.is_dir():
                target = binary_dir / relative.name
                with source.open(item) as incoming, target.open('wb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
            elif relative.name == 'LICENSE.txt':
                (notices / 'LICENSE.txt').write_bytes(source.read(item))
    executable = binary_dir / 'ffmpeg.exe'
    version = checked_run([str(executable), '-version'], capture_output=True, text=True, encoding='utf-8').stdout
    (notices / 'build-version.txt').write_text(version, encoding='utf-8')
    manifest = {'archive': FFMPEG_ARCHIVE, 'sha256': actual,
                'publisher': 'https://github.com/BtbN/FFmpeg-Builds',
                'sourceMatch': re.search(r'\bg([0-9a-f]{7,40})\b', version.splitlines()[0]).group(1)}
    (notices / 'provenance.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def collect_notices(destination):
    destination.mkdir(parents=True, exist_ok=True)
    dependencies = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get('Name', 'unknown')
        dependencies.append({'name': name, 'version': distribution.version})
        folder = destination / re.sub(r'[^a-zA-Z0-9_.-]', '_', name)
        for item in distribution.files or []:
            lowered = str(item).lower()
            if 'dist-info/' not in lowered or not any(word in lowered for word in ('license', 'copying', 'notice', 'authors')):
                continue
            source = Path(distribution.locate_file(item))
            if source.is_file():
                folder.mkdir(exist_ok=True)
                shutil.copy2(source, folder / source.name)
    (destination / 'python-packages.json').write_text(json.dumps(sorted(dependencies, key=lambda x: x['name'].lower()), indent=2), encoding='utf-8')
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file():
        shutil.copy2(python_license, destination / 'Python-LICENSE.txt')


def collect_browser_credits(executable, destination):
    # Chromium keeps full third-party texts, including collapsed sections, here.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
        try:
            page = browser.new_page()
            page.goto('chrome://credits/', wait_until='load')
            credits = page.locator('body').text_content()
            if len(credits or '') < 100000 or 'Redistribution and use' not in credits:
                raise RuntimeError('Chromium license texts could not be collected')
            destination.write_text(credits, encoding='utf-8')
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser-dir', type=Path, required=True, help='Directory containing chrome-win64/chrome.exe')
    parser.add_argument('--no-zip', action='store_true')
    args = parser.parse_args()
    browser = args.browser_dir.resolve()
    if not (browser / 'chrome-win64' / 'chrome.exe').is_file():
        raise SystemExit('The browser directory must contain chrome-win64/chrome.exe')
    runtime = ROOT / 'packaging' / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    provenance = prepare_ffmpeg(ROOT / 'packaging' / 'downloads', runtime)
    print('FFmpeg verified. Building standalone Python executable...', flush=True)
    (ROOT / 'build').mkdir(exist_ok=True)
    with (ROOT / 'build' / 'portable-build.log').open('w', encoding='utf-8') as log:
        try:
            checked_run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                         '--distpath', str(ROOT / 'release' / 'staging'),
                         '--workpath', str(ROOT / 'build' / 'pyinstaller'),
                         str(ROOT / 'packaging' / 'StrokeScape.spec')],
                        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        except subprocess.CalledProcessError:
            print((ROOT / 'build' / 'portable-build.log').read_text(encoding='utf-8')[-12000:])
            raise
    bundle = ROOT / 'release' / 'staging' / 'StrokeScape'
    internal = bundle / '_internal'
    print('Adding offline browser, codecs and license notices...', flush=True)
    shutil.copytree(runtime / 'bin', internal / 'bin', dirs_exist_ok=True)
    shutil.copytree(browser / 'chrome-win64', internal / 'browser' / 'chrome-win64', dirs_exist_ok=True)
    third_party = bundle / 'ThirdParty'
    third_party.mkdir(exist_ok=True)
    shutil.copytree(runtime / 'ffmpeg-notices', third_party / 'FFmpeg', dirs_exist_ok=True)
    collect_notices(third_party / 'Python')
    frontend_notices = third_party / 'Frontend'
    frontend_notices.mkdir(exist_ok=True)
    for name in ('react', 'react-dom', 'lucide-react'):
        shutil.copy2(ROOT / 'node_modules' / name / 'LICENSE', frontend_notices / (name + '-LICENSE.txt'))
    collect_browser_credits(internal / 'browser/chrome-win64/chrome.exe', third_party / 'Chromium-CREDITS.txt')
    shutil.copy2(ROOT / 'packaging' / 'PORTABLE_README.txt', bundle / '使用说明.txt')
    shutil.copy2(ROOT / 'THIRD_PARTY_NOTICES.md', bundle / 'THIRD_PARTY_NOTICES.md')
    for item in ('LICENSE', 'LICENSES.chromium.html'):
        source = browser / 'chrome-win64' / item
        if source.is_file():
            shutil.copy2(source, third_party / ('Chromium-' + item))
    manifest = {'product': 'StrokeScape', 'version': VERSION, 'platform': 'Windows x64',
                'ffmpeg': provenance, 'cudaBundled': False, 'userDataBundled': False}
    (bundle / 'build-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    # Release archives are always made from the generated folder, never the repo.
    if not args.no_zip:
        archive = ROOT / 'release' / f'StrokeScape-{VERSION}-Windows-x64.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target:
            for source in sorted(bundle.rglob('*')):
                if source.is_file():
                    relative = source.relative_to(bundle)
                    if relative.parts[0] == 'UserData':
                        raise RuntimeError('UserData must never enter a release archive')
                    target.write(source, Path('StrokeScape') / relative)
        archives = [archive] + sorted((ROOT / 'release').glob('*-source.zip'))
        (ROOT / 'release' / 'SHA256SUMS.txt').write_text(''.join(f'{checksum(item)}  {item.name}\n' for item in archives), encoding='utf-8')
        print(f'Ready: {archive} ({archive.stat().st_size / 2**20:.1f} MiB)', flush=True)


if __name__ == '__main__':
    main()
