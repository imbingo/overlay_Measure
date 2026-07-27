# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_root = Path(SPECPATH).parent
version_file = project_root / "installer" / "generated_version_info.txt"
sample_data = project_root / "sample_data"

if not version_file.exists():
    raise SystemExit(
        "Missing installer/generated_version_info.txt. "
        "Run scripts/build_release.ps1 instead of invoking this spec directly."
    )

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(sample_data), "sample_data")],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PyQt5",
        "PyQt6",
        "tkinter",
        "matplotlib",
        "scipy",
        "pytest",
        "IPython",
        "pyarrow",
        "zmq",
        "numba",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OverlayMeasure",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(version_file),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="OverlayMeasure",
)
