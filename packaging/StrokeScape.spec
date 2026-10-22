# Build from the project root: python -m PyInstaller packaging/StrokeScape.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

project = Path(SPECPATH).parent
data_files = [
    (str(project / 'web-dist'), 'web-dist'),
    (str(project / 'public' / 'renderer.js'), 'public'),
    (str(project / 'public' / 'recording.js'), 'public'),
]
data_files += collect_data_files('webview')
data_files += copy_metadata('pywebview')

a = Analysis(
    [str(project / 'launch.py')], pathex=[str(project)],
    binaries=[], datas=data_files,
    hiddenimports=[
        'backend.api', 'uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio',
        'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on',
        'webview.platforms.winforms', 'webview.platforms.edgechromium',
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['cupy', 'cupyx', 'scipy', 'torch', 'tensorflow', 'matplotlib',
              'IPython', 'pytest', 'tkinter', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name='StrokeScape', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=False,
          icon=str(project / 'packaging' / 'icon.ico'),
          version=str(project / 'packaging' / 'version-info.txt'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='StrokeScape')
