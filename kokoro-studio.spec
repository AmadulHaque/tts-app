# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — builds 'Kokoro Studio' as a macOS windowed .app.

Usage (from the project root, after installing the `dev` extra):
    uv pip install -e '.[dev]'
    python -m PyInstaller --clean --noconfirm kokoro-studio.spec
    # -> dist/Kokoro Studio.app

Notes:
  * Bundling torch produces a very large app (several GB) and takes a while.
  * misaki + espeakng-loader ship data files and C libs at import time, so we
    collect them explicitly.
  * The .qss styles are written relative to __file__ at runtime; they are
    bundled under app/assets/styles and load fine from the frozen bundle.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH)

datas, binaries, hiddenimports = [], [], []

# G2P + espeak-ng loader carry data / libraries.
for _pkg in ("misaki", "espeakng_loader"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

hiddenimports += collect_submodules("kokoro")
hiddenimports += ["pyloudnorm", "pydub", "soundfile"]

# Bundle the stylesheets next to the frozen app code.
_qss_dir = ROOT / "app" / "assets" / "styles"
datas += [(str(_qss_dir), "app/assets/styles")]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "Tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Kokoro Studio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed app (no terminal on macOS)
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # TODO: point at an .icns for a custom app icon
)

app = BUNDLE(
    exe,
    name="Kokoro Studio",
    icon=None,
    bundle_identifier="com.kokorostudio.app",
    info_plist={
        "NSHighResolutionCapable": True,
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "CFBundleDisplayName": "Kokoro Studio",
        "LSMinimumSystemVersion": "12.0",
    },
)
