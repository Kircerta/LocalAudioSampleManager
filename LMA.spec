# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['lma_main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['soundfile'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LMA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file=None,
    icon=['LMA.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LMA',
)
app = BUNDLE(
    coll,
    name='LMA.app',
    icon='LMA.icns',
    bundle_identifier=None,
)
